import csv
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

    def search_similar_comment(
        self, comment_content: str, revision_id: int, diff_length_limit: int
    ):
        query_embedding = self.embeddings.embed_query(comment_content)
        results = self.db.search(query_embedding)

        for result in results:
            if (
                result.payload["fix_info"]["revision_id"] != revision_id
                and len(result.payload["fix_info"]["fix_patch_diff"])
                < diff_length_limit
            ):
                return result.payload["comment"], result.payload["fix_info"]

        raise Exception("No similar comment found.")


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
    try:
        url = f"https://phabricator.services.mozilla.com/D{revision_id}?id={patch_id}&download=true"
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.HTTPError as e:
        logger.error(f"HTTP error fetching diff: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return None


def generate_prompt(
    comment_content,
    relevant_diff,
    start_line,
    end_line,
    similar_comment,
    fix_info,
    prompt_type,
):
    if prompt_type == "zero-shot":
        prompt = f"""
        CONTEXT:
        You are a code review bot that generates fixes in code given an inline review comment.
        You will be provided with the COMMENT, the LINE NUMBERS the comment is referring to,
        and the relevant DIFF for the file affected. Your goal is to generate a code fix based
        on the COMMENT, LINE NUMBERS, and DIFF provided, and nothing more. Generate ONLY the
        lines you are adding/deleting, indicated by + and -. For example, if you are modifying
        a single line, show that you are deleting (-) the line from the original diff and adding
        (+) the fixed line. The line numbers help to contextualize the changes within the diff.

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
    if prompt_type == "single-shot":
        prompt = f"""
        CONTEXT:
        You are a code review bot that generates fixes in code given an inline review comment.
        You will be provided with the COMMENT, the LINE NUMBERS the comment is referring to,
        and the relevant DIFF for the file affected. Your goal is to generate a code fix based
        on the COMMENT, LINE NUMBERS, and DIFF provided, and nothing more. Generate ONLY the
        lines you are adding/deleting, indicated by + and -. For example, if you are modifying
        a single line, show that you are deleting (-) the line from the original diff and adding
        (+) the fixed line. The line numbers help to contextualize the changes within the diff.
        An EXAMPLE has been provided for your reference.

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


def generate_fixes(
    client, db, generation_limit, diff_length_limits, prompt_types, output_csv
):
    counter = 0
    revision_ids = extract_revision_id_list_from_dataset("data/fixed_comments.json")

    with open(output_csv, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Revision ID",
                "Patch ID",
                "Prompt Type",
                "Length Limit",
                "Precision",
                "Recall",
                "F1",
            ]
        )

        for patch_id, comments in review_data.get_all_inline_comments(lambda c: True):
            revision_id = get_revision_id_from_patch(patch_id)

            if not revision_id:
                logger.error(f"Skipping Patch ID {patch_id} as no revision ID found.")
                continue

            if revision_id not in revision_ids:
                logger.error(
                    f"Skipping Patch ID {patch_id} as revision ID {revision_id} not in dataset."
                )
                continue

            diff = fetch_diff(revision_id, patch_id)

            if not diff:
                logger.error(f"Skipping Patch ID {patch_id} as no diff found.")
                continue

            for comment in comments:
                if counter >= generation_limit:
                    return

                filename = comment.filename

                relevant_diff = extract_relevant_diff(diff, filename)

                if relevant_diff:
                    for prompt_type in prompt_types:
                        if counter >= generation_limit:
                            break

                        for diff_length_limit in diff_length_limits:
                            try:
                                if counter >= generation_limit:
                                    break

                                similar_comment, fix_info = db.search_similar_comment(
                                    comment.content, revision_id, diff_length_limit
                                )

                                prompt = generate_prompt(
                                    comment.content,
                                    relevant_diff,
                                    comment.start_line,
                                    comment.end_line,
                                    similar_comment,
                                    fix_info,
                                    prompt_type,
                                )

                                stream = client.chat.completions.create(
                                    model="gpt-4o",
                                    messages=[{"role": "user", "content": prompt}],
                                    stream=True,
                                )

                                generated_fix = ""
                                for chunk in stream:
                                    if chunk.choices[0].delta.content is not None:
                                        generated_fix += chunk.choices[0].delta.content

                                metrics = compare_fixes(
                                    revision_id,
                                    patch_id,
                                    generated_fix,
                                    "data/fixed_comments.json",
                                )

                                writer.writerow(
                                    [
                                        revision_id,
                                        patch_id,
                                        prompt_type,
                                        diff_length_limit,
                                        metrics["precision"],
                                        metrics["recall"],
                                        metrics["f1"],
                                    ]
                                )

                                counter += 1

                            except Exception as e:
                                logger.error(
                                    f"Error processing Comment ID {comment.id} with {prompt_type} and limit {diff_length_limit}: {e}"
                                )

                else:
                    print(f"No relevant diff found for Comment ID {comment.id}.\n")


def extract_revision_id_list_from_dataset(dataset_file):
    revision_ids = []

    with open(dataset_file, "r") as f:
        for line in f:
            data = json.loads(line)
            revision_ids.append(data["revision_id"])

    return revision_ids


def calculate_metrics(reference_fix, generated_fix):
    reference_tokens = reference_fix.split()
    generated_tokens = generated_fix.split()

    common_tokens = set(reference_tokens) & set(generated_tokens)
    precision = len(common_tokens) / len(generated_tokens) if generated_tokens else 0
    recall = len(common_tokens) / len(reference_tokens) if reference_tokens else 0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def find_fix_in_dataset(
    revision_id,
    initial_patch_id,
    dataset_file,
):
    with open(dataset_file, "r") as f:
        for line in f:
            data = json.loads(line)
            if (
                data["revision_id"] == revision_id
                and data["initial_patch_id"] == initial_patch_id
            ):
                return data["fix_patch_diff"]
    return None


def compare_fixes(revision_id, initial_patch_id, generated_fix, dataset_file):
    reference_fix = find_fix_in_dataset(revision_id, initial_patch_id, dataset_file)

    if reference_fix:
        metrics = calculate_metrics(reference_fix, generated_fix)
        return metrics
    else:
        print(
            f"No matching fix found in the dataset for Revision {revision_id} and Patch {initial_patch_id}."
        )


def main():
    CREATE_DB = False

    db = FixCommentDB(LocalQdrantVectorDB(collection_name="fix_comments"))

    if CREATE_DB:
        db.db.delete_collection()
        db.db.setup()
        db.upload_dataset("data/fixed_comments.json")

    client = openai.OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    prompt_types = ["zero-shot", "single-shot"]
    diff_length_limits = [100, 1000, 10000]
    output_csv = "metrics_results.csv"
    generation_limit = len(prompt_types) * len(diff_length_limits) + 20

    generate_fixes(
        client=client,
        db=db,
        generation_limit=generation_limit,
        prompt_types=prompt_types,
        diff_length_limits=diff_length_limits,
        output_csv=output_csv,
    )


if __name__ == "__main__":
    main()
