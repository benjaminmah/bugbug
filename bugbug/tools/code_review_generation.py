import json
import logging
import re

import openai
import requests
from langchain_openai import OpenAIEmbeddings
from libmozdata.phabricator import PhabricatorAPI
from qdrant_client import QdrantClient

from bugbug.tools.code_review import PhabricatorReviewData
from bugbug.utils import get_secret
from bugbug.vectordb import QdrantVectorDB, VectorPoint

review_data = PhabricatorReviewData()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
api = PhabricatorAPI(get_secret("PHABRICATOR_TOKEN"))


class LocalQdrantVectorDB(QdrantVectorDB):
    def __init__(self, collection_name: str, location: str = "http://localhost:6333"):
        self.collection_name = collection_name
        self.client = QdrantClient(location=location)

    def setup(self):
        super().setup()

    def delete_collection(self):
        self.client.delete_collection(self.collection_name)


class FixCommentDB:
    def __init__(self, db: LocalQdrantVectorDB):
        self.db = db
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-large", api_key=get_secret("OPENAI_API_KEY")
        )

    def line_to_vector_point(self, line: str):
        data = json.loads(line)
        comment_content = data["comment"]["content"]

        embedding = self.embeddings.embed_query(comment_content)

        vector_point = VectorPoint(
            id=data["comment"]["id"],
            vector=embedding,
            payload={"comment": comment_content, "fix_info": data},
        )
        return vector_point

    def upload_dataset(self, dataset_file: str):
        with open(dataset_file, "r") as f:
            points = []
            for line in f:
                vector_point = self.line_to_vector_point(line)
                points.append(vector_point)
            self.db.insert(points)

    def search_similar_comment(self, comment_content: str):
        query_embedding = self.embeddings.embed_query(comment_content)
        results = self.db.search(query_embedding)

        for result in results:
            return result.payload["comment"], result.payload["fix_info"]


def fetch_patch_diff(patch_id):
    diffs = api.search_diffs(diff_id=patch_id)
    if diffs:
        return diffs
    else:
        logger.error(f"No diffs found for patch ID: {patch_id}")
        return None


def extract_relevant_diff(patch_diff, filename):
    file_diff_pattern = rf"diff --git a/{re.escape(filename)} b/{re.escape(filename)}\n.*?(?=\ndiff --git|$)"
    match = re.search(file_diff_pattern, patch_diff, re.DOTALL)

    if match:
        return match.group(0)
    else:
        logger.error(f"No diff found for file: {filename}")
        return None


def get_revision_id_from_patch(patch_id):
    diffs = api.search_diffs(diff_id=patch_id)

    if diffs:
        revision_phid = diffs[0]["revisionPHID"]

        revision = api.load_revision(rev_phid=revision_phid)

        return revision["id"]
    else:
        logger.error(f"No diffs found for patch ID: {patch_id}")
        return None


def fetch_diff(revision_id, patch_id):
    url = f"https://phabricator.services.mozilla.com/D{revision_id}?id={patch_id}&download=true"
    response = requests.get(url)
    if response.status_code == 200:
        return response.text
    else:
        raise Exception(f"Failed to download diff from URL: {url}")


def generate_prompt(
    comment_content, relevant_diff, start_line, end_line, similar_comment, fix_info
):
    prompt = f"""
    CONTEXT:
    You are a code review bot that generates fixes in code given an inline review comment. You will be provided with the COMMENT, the LINE NUMBERS the comment is referring to, and the relevant DIFF for the file affected. Your goal is to generate a code fix based on the COMMENT and DIFF provided, and nothing more. Generate ONLY the lines you are adding/deleting, indicated by + and -. For example, if you are modifying a single line, show that you are deleting (-) the line from the original diff and adding (+) the fixed line. An EXAMPLE is also provided below.

    EXAMPLE:
    COMMENT:
    "{similar_comment}"

    LINE NUMBERS:
    {fix_info["comment"]["start_line"]}-{fix_info["comment"]["end_line"]}

    DIFF:
    ```
    {fetch_diff(fix_info["revision_id"], fix_info["initial_patch_id"])}
    ```

    FIX:
    ```
    {fix_info["fix_patch_diff"]}
    ```

    YOUR TURN:
    COMMENT:
    "{comment_content}"

    LINE NUMBERS:
    {start_line}-{end_line}

    DIFF:
    ```
    {relevant_diff}
    ```

    FIX:
    """
    return prompt


def generate_fixes(client, db):
    limit = 3
    counter = 0

    for patch_id, comments in review_data.get_all_inline_comments(lambda c: True):
        revision_id = get_revision_id_from_patch(patch_id)

        if not revision_id:
            logger.error(f"Skipping Patch ID {patch_id} as no revision ID found.")
            continue

        diff = fetch_diff(revision_id, patch_id)

        if not diff:
            logger.error(f"Skipping Patch ID {patch_id} as no diff found.")
            continue

        for comment in comments:
            filename = comment.filename

            relevant_diff = extract_relevant_diff(diff, filename)

            if relevant_diff:
                similar_comment, fix_info = db.search_similar_comment(comment.content)

                prompt = generate_prompt(
                    comment.content,
                    relevant_diff,
                    comment.start_line,
                    comment.end_line,
                    similar_comment,
                    fix_info,
                )
                print(f"Prompt for {comment.id}:\n{prompt}\n")

                stream = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                )

                print(f"Generated fix for {comment.id}:\n")
                for chunk in stream:
                    if chunk.choices[0].delta.content is not None:
                        print(chunk.choices[0].delta.content, end="")
            else:
                print(f"No relevant diff found for Comment ID {comment.id}.\n")

        counter += 1

        if counter >= limit:
            break


def main():
    CREATE_DB = False

    db = FixCommentDB(LocalQdrantVectorDB(collection_name="fix_comments"))

    if CREATE_DB:
        db.db.delete_collection()
        db.db.setup()
        db.upload_dataset("dataset.json")

    client = openai.OpenAI(api_key=get_secret("OPENAI_API_KEY"))
    generate_fixes(client, db)


if __name__ == "__main__":
    main()
