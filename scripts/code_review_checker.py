import csv
import os
from collections import defaultdict

from libmozdata.phabricator import PhabricatorAPI
from unidiff import PatchSet

import config
from bugbug import db, phabricator

# define the required key phabricator (config.PHABRICATOR_API_KEY)
db.download(phabricator.REVISIONS_DB)

# download all available revisions
rev = PhabricatorAPI(config.PHABRICATOR_API_KEY)

phab = PhabricatorAPI(
    config.PHABRICATOR_API_KEY, "https://phabricator.services.mozilla.com/api/"
)


def get_target_revisions():
    data_dict = defaultdict(lambda: {"inline_comment_ids": [], "suggestion_ids": []})

    with open("input/input.csv", mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            revision_id = int(row["revision_id"])
            inline_comment_id = int(row["inline_comment_id"])
            suggestion_id = int(row["suggestion_id"])

            data_dict[revision_id]["inline_comment_ids"].append(inline_comment_id)
            data_dict[revision_id]["suggestion_ids"].append(suggestion_id)

    return dict(data_dict)


def collect_phid_from_comment_ids(transactions, comment_ids):
    comment_phids = {}

    for transaction in transactions:
        if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
            for comment in transaction["comments"]:
                if comment["id"] in comment_ids:
                    comment_phids[comment["phid"]] = comment["id"]

    return comment_phids


def get_associated_hunk_from_comment_ids(transaction, target_line, path):
    patch = PatchSet(phab.load_raw_diff(transaction["diff"]["id"]))

    patch_count = 1

    for patched_file in patch:
        if patched_file.path == path:
            # Iterate through the hunks to find the line in question
            for hunk in patched_file:
                for line in hunk:
                    # Check if the line is part of the original or modified file
                    if line.target_line_no == target_line:
                        return patch_count

        patch_count += 1

    return None


def check_for_replies_on_target_comments(transactions, comment_ids):
    comment_phids = collect_phid_from_comment_ids(transactions, comment_ids)
    comment_status = {}
    comment_status_hunks = {}
    comment_status_hunks_output = {}

    for transaction in transactions:
        if (
            len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0
        ) and transaction["fields"]["replyToCommentPHID"] in comment_phids.keys():
            comment_status[
                comment_phids.get(transaction["fields"]["replyToCommentPHID"])
            ] = True
            associated_hunk = get_associated_hunk_from_comment_ids(
                transaction["fields"],
                transaction["fields"]["line"],
                transaction["fields"]["path"],
            )
            comment_status_hunks[associated_hunk] = [
                comment_phids.get(transaction["fields"]["replyToCommentPHID"])
            ]

    for comment_id in comment_ids:
        if comment_id not in comment_status:
            comment_status[comment_id] = False

    for key, value in comment_status_hunks.items():
        if len(value) > 1:
            for comment_id in value:
                comment_status_hunks_output[comment_id] = True

    for comment_id in comment_ids:
        if comment_id not in comment_status_hunks_output:
            comment_status_hunks_output[comment_id] = False

    return comment_status, comment_status_hunks_output


def check_for_comments_in_hunk(transactions, comment_ids, hunk_range=0):
    comment_information = {}
    same_hunk_comments = defaultdict(list)

    # Filter inline comments and populate comment_information
    for transaction in transactions:
        if (
            transaction["type"] != "inline"
            or not transaction["fields"]
            or not transaction["comments"]
        ):
            continue

        for comment in transaction["comments"]:
            if comment["id"] in comment_ids:
                comment_information[comment["id"]] = (
                    transaction["fields"]["line"],
                    transaction["fields"]["path"],
                    transaction["dateCreated"],
                )

    # Check for comments in the same hunk
    for transaction in transactions:
        if (
            transaction["type"] != "inline"
            or not transaction["fields"]
            or not transaction["comments"]
        ):
            continue

        current_comment_line = transaction["fields"]["line"]
        current_comment_file_path = transaction["fields"]["path"]

        for comment in transaction["comments"]:
            for comment_id, (
                line_number,
                file_path,
                date_created,
            ) in comment_information.items():
                if (
                    comment["dateCreated"] > date_created
                    and comment["id"] != comment_id
                    and file_path == current_comment_file_path
                ):
                    if (
                        line_number - hunk_range
                        <= current_comment_line
                        <= line_number + hunk_range
                    ):
                        same_hunk_comments[comment_id].append(comment)
    return same_hunk_comments


def generate_report(
    target_file,
    comments_report,
    hunk_report,
    revised_lines_status,
    revised_hunks_status,
    same_line_comment_report,
    same_hunk_comment_report,
    target_revision,
    revision_status,
    suggestion_ids,
):
    file_exists = os.path.isfile(target_file)
    file_is_empty = os.stat(target_file).st_size == 0 if file_exists else True

    with open(target_file, mode="a", newline="") as file:
        writer = csv.writer(file)

        if file_is_empty:
            writer.writerow(
                [
                    "Revision",
                    "Status",
                    "Suggestion_ID" "Comment",
                    "Thread_Line",
                    "Thread_Hunk",
                    "Revised_Line",
                    "Revised_Hunk",
                    "Comment_Line",
                    "Comment_Line_Comments",
                    "Comment_Hunk",
                    "Comment_Hunk_Comments",
                ]
            )

        for comment_report, status_thread_line in comments_report.items():
            same_line_exists = bool(same_line_comment_report.get(comment_report, {}))
            hunk_exists = bool(same_hunk_comment_report.get(comment_report, {}))
            status_thread_hunk = hunk_report.get(comment_report, False)
            revised_line_status = revised_lines_status.get(comment_report, False)
            revised_hunk_status = revised_hunks_status.get(comment_report, False)

            writer.writerow(
                [
                    target_revision,
                    revision_status,
                    suggestion_ids,
                    comment_report,
                    status_thread_line,
                    status_thread_hunk,
                    revised_line_status,
                    revised_hunk_status,
                    same_line_exists,
                    same_line_comment_report.get(comment_report, {}),
                    hunk_exists,
                    same_hunk_comment_report.get(comment_report, {}),
                ]
            )


def check_status_revised_line_and_hunks(transactions, comment_ids, accepted_diff):
    status_lines = {}
    status_hunks = {}

    for transaction in transactions:
        if len(transaction["fields"]) > 0 and len(transaction["comments"]) > 0:
            for comment in transaction["comments"]:
                if (
                    comment["id"] in comment_ids
                    and transaction["fields"]["isDone"] is True
                ):
                    line_number = transaction["fields"]["line"]
                    file = transaction["fields"]["path"]
                    status_line, status_hunk = is_line_and_hunk_changed_after_comment(
                        accepted_diff, line_number, file, transaction["fields"]
                    )
                    status_lines[comment["id"]] = status_line
                    status_hunks[comment["id"]] = status_hunk

    return status_lines, status_hunks


def is_line_and_hunk_changed_after_comment(diff, line, file, target_diff):
    diff_aux = phab.load_raw_diff(target_diff["diff"]["id"])
    line_content = get_line_from_patch(diff_aux, file, line)

    if diff == diff_aux:
        return [False, False]

    patch = PatchSet(diff)
    status_hunk = get_interval(diff_aux, line, file, patch)
    state_line = True

    if line_content is not None:
        for patched_file in patch:
            if patched_file.path == file:
                # Iterate through the hunks to find the line in question
                for hunk in patched_file:
                    for line in hunk:
                        # Check if the line is part of the original or modified file
                        if line_content == line.value.strip():
                            state_line = False
                            break

    return [state_line, status_hunk]


def get_line_from_patch(patch_content, file_path, line_number, original=True):
    patch = PatchSet(patch_content)

    # Find the file in the patch that corresponds to the file_path
    for patched_file in patch:
        if patched_file.path == file_path:
            # Iterate through the hunks to find the line in question
            for hunk in patched_file:
                for line in hunk:
                    # Check if the line is part of the original or modified file
                    if original and line.target_line_no == line_number:
                        return line.value.strip()
                    elif not original and line.target_line_no == line_number:
                        return line.value.strip()

    return None


def get_interval(target_diff, line_number, file, final_patch):
    patch = PatchSet(target_diff)

    begin = 0
    end = 0

    for patched_file in patch:
        if patched_file.path == file:
            # Iterate through the hunks to find the line in question
            for hunk in patched_file:
                for line in hunk:
                    if (
                        line.target_line_no is not None
                        and line.target_line_no <= line_number
                        and line.target_line_no + hunk.target_length >= line_number
                    ):
                        # if line.target_line_no <= line_number:
                        if line_number - line.target_line_no <= 5:
                            begin = line.target_line_no
                        else:
                            begin = line_number - 5

                        # if line.target_line_no + hunk.target_length >= line_number:
                        if (
                            line.target_line_no + hunk.target_length
                        ) - line_number <= 5:
                            end = (
                                line.target_line_no + hunk.target_length
                            ) - line_number
                        else:
                            end = line_number + 5

                        return get_interval_lines(patch, file, begin, end, final_patch)

    return get_interval_lines(patch, file, begin, end)


def get_interval_lines(patch, file, begin, end, final_diff):
    lines = {}
    context_lines = []
    context_lines_status = {}

    if begin == 0 and end == 0:
        return lines

    for patched_file in patch:
        if patched_file.path == file:
            # Iterate through the hunks to find the line in question
            for hunk in patched_file:
                for line in hunk:
                    if (
                        line.target_line_no is not None
                        and line.target_line_no >= begin
                        and line.target_line_no <= end
                    ):
                        lines[line.target_line_no] = line
                        context_lines.append(line.value)

    for patched_file in final_diff:
        if patched_file.path == file:
            # Iterate through the hunks to find the line in question
            for hunk in patched_file:
                for line in hunk:
                    if line.value in context_lines:
                        context_lines_status[line.value] = True

    if len(context_lines_status) != len(context_lines):
        return True

    return False


def run_analysis(target_file):
    revisions = get_target_revisions()

    for revision in phabricator.get_revisions():
        if revision["id"] in revisions.keys():
            try:
                accepted_diff = phab.load_raw_diff(
                    phab.load_revision(revision["phid"])["fields"]["diffID"]
                )
                (
                    revised_lines_status,
                    revised_hunks_status,
                ) = check_status_revised_line_and_hunks(
                    revision["transactions"],
                    revisions.get(revision["id"])["inline_comment_ids"],
                    accepted_diff,
                )

                revision_replies, hunk_replies = check_for_replies_on_target_comments(
                    revision["transactions"],
                    revisions.get(revision["id"])["inline_comment_ids"],
                )

                same_line_comments = check_for_comments_in_hunk(
                    transactions=revision["transactions"],
                    comment_ids=revisions.get(revision["id"])["inline_comment_ids"],
                    hunk_range=0,
                )

                hunk_comments = check_for_comments_in_hunk(
                    transactions=revision["transactions"],
                    comment_ids=revisions.get(revision["id"])["inline_comment_ids"],
                    hunk_range=10,
                )

                generate_report(
                    target_file,
                    revision_replies,
                    hunk_replies,
                    revised_lines_status,
                    revised_hunks_status,
                    same_line_comments,
                    hunk_comments,
                    revision["id"],
                    revision["fields"]["status"]["value"],
                    revisions.get(revision["id"])["suggestion_ids"],
                )

            except Exception as e:
                print(e)


if __name__ == "__main__":
    run_analysis("comment-status-final.csv")
