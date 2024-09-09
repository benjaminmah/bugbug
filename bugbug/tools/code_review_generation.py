import logging
import re

import requests
from libmozdata.phabricator import PhabricatorAPI

from bugbug.tools.code_review import PhabricatorReviewData
from bugbug.utils import get_secret

review_data = PhabricatorReviewData()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
api = PhabricatorAPI(get_secret("PHABRICATOR_TOKEN"))


def fetch_patch_diff(patch_id):
    diffs = api.search_diffs(diff_id=patch_id)
    if diffs:
        return diffs
    else:
        logger.error(f"No diffs found for patch ID: {patch_id}")
        return None


def extract_relevant_diff(patch_diff, filename, start_line=None, end_line=None):
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


def create_gpt4_prompt(comment_content, relevant_diff, start_line, end_line):
    prompt = f"""
    ### Task
    The following is a code review comment regarding lines {start_line} to {end_line} in the provided code diff. Generate the necessary code change to address the comment.

    ### Code Review Comment
    "{comment_content}"

    ### Code Diff (affected lines {start_line}-{end_line})
    ```
    {relevant_diff}
    ```

    ### Instruction
    Please generate a code fix based on the comment and the diff. Only return the modified code, no additional text.
    """
    return prompt


def process_comments():
    for patch_id, comments in review_data.get_all_inline_comments(lambda c: True):
        print(f"Processing Patch ID: {patch_id}")

        revision_id = get_revision_id_from_patch(patch_id)

        if not revision_id:
            logger.error(f"Skipping Patch ID {patch_id} as no revision ID found.")
            continue

        # Fetch the diff for the patch
        diff = fetch_diff(revision_id, patch_id)

        if not diff:
            logger.error(f"Skipping Patch ID {patch_id} as no diff found.")
            continue

        for comment in comments:
            filename = comment.filename

            relevant_diff = extract_relevant_diff(diff, filename)

            if relevant_diff:
                prompt = create_gpt4_prompt(
                    comment.content, relevant_diff, comment.start_line, comment.end_line
                )
                print(f"GPT-4 Prompt for Comment ID {comment.id}:\n{prompt}\n")

                # Send the prompt to GPT-4 (this part depends on how you handle API calls)
                # response = openai.Completion.create(
                #    model="gpt-4",
                #    prompt=prompt,
                #    max_tokens=500
                # )
                # print(f"GPT-4 Response: {response['choices'][0]['text']}")
            else:
                print(f"No relevant diff found for Comment ID {comment.id}.\n")

        break


if __name__ == "__main__":
    process_comments()
