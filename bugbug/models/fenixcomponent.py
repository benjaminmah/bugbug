# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
from datetime import datetime, timezone

import dateutil.parser
import xgboost
from dateutil.relativedelta import relativedelta
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImblearnPipeline
from imblearn.under_sampling import RandomUnderSampler
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction import DictVectorizer
from sklearn.pipeline import Pipeline

from bugbug import bug_features, bugzilla, feature_cleanup, utils
from bugbug.model import BugModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FenixComponentModel(BugModel):
    def __init__(self, lemmatization=False):
        BugModel.__init__(self, lemmatization)

        self.cross_validation_enabled = False
        self.calculate_importance = False

        feature_extractors = [
            bug_features.HasSTR(),
            bug_features.Severity(),
            bug_features.Keywords(),
            bug_features.HasCrashSignature(),
            bug_features.HasURL(),
            bug_features.HasW3CURL(),
            bug_features.HasGithubURL(),
            bug_features.Whiteboard(),
            bug_features.Patches(),
            bug_features.Landings(),
        ]

        cleanup_functions = [
            feature_cleanup.fileref(),
            feature_cleanup.url(),
            feature_cleanup.synonyms(),
        ]

        self.extraction_pipeline = Pipeline(
            [
                (
                    "bug_extractor",
                    bug_features.BugExtractor(feature_extractors, cleanup_functions),
                ),
            ]
        )

        self.clf = ImblearnPipeline(
            [
                (
                    "union",
                    ColumnTransformer(
                        [
                            ("data", DictVectorizer(), "data"),
                            ("title", self.text_vectorizer(), "title"),
                            ("comments", self.text_vectorizer(), "comments"),
                        ]
                    ),
                ),
                ("smote", SMOTE(random_state=42)),
                ("undersample", RandomUnderSampler(random_state=42)),
                (
                    "estimator",
                    xgboost.XGBClassifier(n_jobs=utils.get_physical_cpu_count()),
                ),
            ]
        )

    def get_labels(self):
        classes = {}

        date_limit = datetime.now(timezone.utc) - relativedelta(years=2)

        for bug_data in bugzilla.get_bugs():
            if bug_data["product"] != "Fenix":
                continue

            moved_out_by_bot = False
            moved_back_to_general_by_user = False
            component = None

            for history_entry in bug_data.get("history", []):
                for change in history_entry.get("changes", []):
                    if change["field_name"] == "component":
                        if (
                            change["removed"] == "General"
                            and history_entry["who"]
                            == "release-mgmt-account-bot@mozilla.tld"
                        ):
                            moved_out_by_bot = True
                            component = change["added"]
                        elif (
                            component
                            and change["removed"] == component
                            and history_entry["who"]
                            != "release-mgmt-account-bot@mozilla.tld"
                            and moved_out_by_bot
                        ):
                            moved_back_to_general_by_user = True

            if moved_out_by_bot and moved_back_to_general_by_user:
                print(
                    f"Bug ID {bug_data['id']} was moved out of General by the bot and then moved back to General by someone else."
                )

            # Exclude 'General' because it contains bugs that may belong to other components, thus introducing noise.
            if (
                bug_data["component"] == "General"
                and not moved_out_by_bot
                and not moved_back_to_general_by_user
            ):
                continue

            if dateutil.parser.parse(bug_data["creation_time"]) < date_limit:
                continue

            classes[int(bug_data["id"])] = bug_data["component"]

        return classes, set(classes.values())

    def get_feature_names(self):
        return self.clf.named_steps["union"].get_feature_names_out()
