import argparse
import logging
import os
import re

import hglib
import orjson
from libmozdata.phabricator import PhabricatorAPI

from bugbug import db, phabricator, repository, selenium_test
from bugbug.phabricator import fetch_interdiff
from bugbug.tools.code_review import PhabricatorReviewData
from bugbug.utils import (
    get_secret,
    setup_libmozdata,
    zstd_compress,
)

review_data = PhabricatorReviewData()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

setup_libmozdata()
api = PhabricatorAPI(get_secret("PHABRICATOR_TOKEN"))


class NoDiffsFoundException(Exception):
    def __init__(self, patch_id):
        super().__init__(f"No diffs found for the given patch ID: {patch_id}")
        self.patch_id = patch_id


class NoTransactionsFoundException(Exception):
    def __init__(self, patch_id):
        super().__init__(f"No transactions found for the given patch ID: {patch_id}")
        self.patch_id = patch_id


class NoDiffFoundForPHIDException(Exception):
    def __init__(self, phid):
        super().__init__(f"No diff found for PHID {phid}")
        self.phid = phid


def load_revisions_maps():
    diff_id_to_revision = {}
    diff_phid_to_id = {}

    for revision in phabricator.get_revisions():
        for transaction in revision["transactions"]:
            if transaction.get("fields", {}).get("diff") is None:
                continue

            diff_id_to_revision[transaction["fields"]["diff"]["id"]] = revision
            diff_phid_to_id[transaction["fields"]["diff"]["phid"]] = transaction[
                "fields"
            ]["diff"]["id"]

    return diff_id_to_revision, diff_phid_to_id


def find_recent_update(transactions, comment_date_modified):
    updates = [
        transaction
        for transaction in transactions
        if transaction["type"] == "update"
        and transaction["dateModified"] <= comment_date_modified
    ]
    return max(
        updates, key=lambda transaction: transaction["dateModified"], default=None
    )


def extract_relevant_diff(patch_diff, filename):
    file_diff_pattern = rf"diff --git a/{re.escape(filename)} b/{re.escape(filename)}\n.*?(?=\ndiff --git|$)"
    match = re.search(file_diff_pattern, patch_diff, re.DOTALL)

    if match:
        return match.group(0)
    else:
        return None


# def process_comments(limit, diff_length_limit):
#     patch_count = 0
#     diff_id_to_revisions_map, diff_phid_to_id = load_revisions_maps()

#     for patch_id, comments in review_data.get_all_inline_comments(lambda c: True):
#         ## START OF NEW SECTION ##
#         # Skip patches with more than one comment
#         if len(comments) != 1:
#             continue
#         ## END OF NEW SECTION ##


#         revision_info = diff_id_to_revisions_map[patch_id]
#         transactions = revision_info["transactions"]

#         resolved_comments = [comment for comment in comments if comment.is_done]

#         if not resolved_comments:
#             continue

#         for comment in comments:
#             comment_date_modified = comment.date_modified
#             most_recent_update = find_recent_update(transactions, comment_date_modified)
#             if not most_recent_update:
#                 continue

#             try:
#                 fix_patch_id = diff_phid_to_id[most_recent_update["fields"]["new"]]
#             except KeyError:
#                 diffs = api.search_diffs(diff_phid=most_recent_update["fields"]["new"])
#                 if not diffs:
#                     raise NoDiffFoundForPHIDException(
#                         most_recent_update["fields"]["new"]
#                     )
#                 fix_patch_id = diffs[0]["id"]

#             # If the most recent patch is the original patch itself, skip it
#             if fix_patch_id == patch_id:
#                 continue

#             revision_phid = revision_info["phid"]
#             revision_id = revision_info["id"]
#             bug_id = revision_info["fields"]["bugzilla.bug-id"]

#             try:
#                 previous_patch_id = diff_phid_to_id[most_recent_update["fields"]["old"]]
#             except Exception:
#                 diffs = api.search_diffs(diff_phid=most_recent_update["fields"]["old"])
#                 if not diffs:
#                     raise NoDiffFoundForPHIDException(
#                         most_recent_update["fields"]["old"]
#                     )
#                 previous_patch_id = diffs[0]["id"]

#             try:
#                 patch_diff = fetch_diff_from_url(
#                     revision_id, previous_patch_id, fix_patch_id
#                 )
#             except Exception as e:
#                 logger.error(f"Failed to fetch diff: {e}")
#                 continue

#             if len(patch_diff) > diff_length_limit:
#                 continue

#             relevant_diff = extract_relevant_diff(patch_diff, comment.filename)

#             if relevant_diff:
#                 data = {
#                     "bug_id": bug_id,
#                     "revision_id": revision_id,
#                     "revision_phid": revision_phid,
#                     "initial_patch_id": patch_id,
#                     "fix_patch_id": fix_patch_id,
#                     "previous_patch_id": previous_patch_id,
#                     "comment": comment.__dict__,
#                     "fix_patch_diff": relevant_diff,
#                 }
#                 yield data

#         patch_count += 1
#         if patch_count >= limit:
#             break


def process_comments(limit, diff_length_limit, phabricator_scraper):
    patch_count = 0
    diff_id_to_revisions_map, diff_phid_to_id = load_revisions_maps()

    patches_by_revision = {}
    for patch_id, comments in review_data.get_all_inline_comments(lambda c: True):
        revision_info = diff_id_to_revisions_map.get(patch_id)
        if not revision_info:
            continue

        revision_id = revision_info["id"]
        has_comments = len(comments) > 0

        if revision_id not in patches_by_revision:
            patches_by_revision[revision_id] = []

        patches_by_revision[revision_id].append((patch_id, has_comments))

    for revision_id in patches_by_revision:
        patches_by_revision[revision_id].sort(key=lambda x: x[0])

    for patch_id, comments in review_data.get_all_inline_comments(lambda c: True):
        # Skip patches with more than one comment
        if len(comments) != 1:
            continue

        revision_info = diff_id_to_revisions_map[patch_id]
        # cutoff_timestamp = datetime(2023, 10, 31).timestamp()
        # dateCreated = revision_info["fields"]["dateCreated"]

        # if dateCreated <= cutoff_timestamp:
        #     continue

        revision_id = revision_info["id"]
        transactions = revision_info["transactions"]

        updates_after_current = [
            transaction
            for transaction in transactions
            if transaction["type"] == "update" and transaction["id"] > patch_id
        ]
        if len(updates_after_current) > 3:
            continue

        # Skip if there are comments on subsequent patches within the same revision
        if not has_no_comments_after_within_revision(
            patch_id, revision_id, patches_by_revision
        ):
            continue

        resolved_comments = [comment for comment in comments if comment.is_done]

        if not resolved_comments:
            continue

        # Get the final patch ID from the transactions
        final_update = max(
            (
                transaction
                for transaction in transactions
                if transaction["type"] == "update"
            ),
            key=lambda t: t["dateModified"],
            default=None,
        )

        if not final_update:
            logger.warning(f"No final update found for patch {patch_id}")
            continue

        try:
            final_patch_id = diff_phid_to_id[final_update["fields"]["new"]]
        except KeyError:
            diffs = api.search_diffs(diff_phid=final_update["fields"]["new"])
            if not diffs:
                raise NoDiffFoundForPHIDException(final_update["fields"]["new"])
            final_patch_id = diffs[0]["id"]

        # If the final patch is the same as the original patch, skip it
        if final_patch_id == patch_id:
            continue

        revision_phid = revision_info["phid"]
        revision_id = revision_info["id"]
        bug_id = revision_info["fields"]["bugzilla.bug-id"]

        try:
            patch_diff = fetch_interdiff(revision_id, patch_id, final_patch_id)
        except Exception as e:
            logger.error(f"Failed to fetch diff: {e}")
            continue

        if len(patch_diff) > diff_length_limit or len(patch_diff) == 0:
            continue

        if revision_id in [97437, 112132, 113979, 123995, 136358, 143624, 146896]:
            continue

        for comment in comments:
            # relevant_diff = extract_relevant_diff(patch_diff, comment.filename)
            file_path = comment.filename
            raw_file_content = None
            raw_file_content = phabricator_scraper.get_raw_file_content(
                revision_id, patch_id, final_patch_id, file_path
            )

            if raw_file_content == "":
                print("Could not find file")
                print(
                    f"Params: {revision_id}, {patch_id}, {final_patch_id}, {file_path}"
                )
                continue

            # if relevant_diff:
            data = {
                "bug_id": bug_id,
                "revision_id": revision_id,
                "revision_phid": revision_phid,
                "initial_patch_id": patch_id,
                "final_patch_id": final_patch_id,
                "raw_file_content": raw_file_content,
                "comment": comment.__dict__,
                "fix_patch_diff": patch_diff,
                # "fix_patch_diff": relevant_diff,
            }
            yield data

        patch_count += 1
        if patch_count >= limit:
            break


def has_no_comments_after_within_revision(patch_id, revision_id, patches_by_revision):
    if revision_id not in patches_by_revision:
        raise KeyError(f"Revision ID {revision_id} not found in patches_by_revision")

    sorted_patches = patches_by_revision[revision_id]

    for i, (current_patch_id, has_comments) in enumerate(sorted_patches):
        if current_patch_id == patch_id:
            for _, next_has_comments in sorted_patches[i + 1 :]:
                if next_has_comments:
                    return False
            return True

    raise KeyError(f"Patch ID {patch_id} not found in revision {revision_id}")


def get_file_content(repo_path, commit_hash, file_path):
    """Fetches the raw file content at a specific commit in a local Mercurial repository.

    Args:
        repo_path (str): Path to the Mercurial repository.
        commit_hash (str): The commit hash at which to retrieve the file.
        file_path (str): Path of the file in the repository.

    Returns:
        str: The file content at the specified commit.
    """
    client = hglib.open(repo_path)

    try:
        file_content = client.cat([file_path.encode()], rev=commit_hash.encode())
        return file_content.decode("utf-8")
    except hglib.error.CommandError:
        raise FileNotFoundError(f"File {file_path} not found at commit {commit_hash}")


def download_databases() -> None:
    logger.info("Cloning Mercurial database...")
    repository.clone(repo_dir="hg_dir")


def main():
    parser = argparse.ArgumentParser(description="Process patch reviews.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of patches to process. No limit if not specified.",
    )
    parser.add_argument(
        "--diff-length-limit",
        type=int,
        default=1000,
        help="Limit the maximum allowed diff length. Default 1000 if not specified.",
    )

    args = parser.parse_args()

    limit = args.limit or float("inf")
    diff_length_limit = args.diff_length_limit or float("inf")

    os.makedirs("patches", exist_ok=True)

    db.download(phabricator.REVISIONS_DB)
    download_databases()

    phabricator_scraper = selenium_test.PhabricatorScraper()

    with open(phabricator.FIXED_COMMENTS_DB, "wb") as dataset_file_handle:
        for data in process_comments(
            limit=limit,
            diff_length_limit=diff_length_limit,
            phabricator_scraper=phabricator_scraper,
        ):
            dataset_file_handle.write(orjson.dumps(data) + b"\n")

    zstd_compress(phabricator.FIXED_COMMENTS_DB)
    phabricator_scraper.close()


if __name__ == "__main__":
    main()
