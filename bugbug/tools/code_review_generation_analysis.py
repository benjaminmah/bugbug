import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

df = pd.read_csv("metrics_results.csv")
df.fillna(0, inplace=True)

df["Qualitative Feedback Binary"] = df["Qualitative Feedback"].apply(
    lambda x: 1 if x.startswith("YES") else 0
)

df["Comment Length"] = df["Comment"].apply(len)

df = df.sort_values(by="Qualitative Feedback Binary", ascending=False).drop_duplicates(
    subset=[
        "Revision ID",
        "Patch ID",
        "Prompt Type",
        "Length Limit",
        "Hunk Size",
        "Comment",
    ],
    keep="first",
)

df["Prompt Type"] = df["Prompt Type"].astype("category")
df["Length Limit"] = df["Length Limit"].astype("category")
df["Hunk Size"] = df["Hunk Size"].astype("category")

df["Composite Score"] = (
    0.2 * df["Precision"]
    + 0.2 * df["Recall"]
    + 0.1 * df["F1"]
    + 0.5 * df["Qualitative Feedback Binary"]
)

df_positive_feedback = df[df["Qualitative Feedback Binary"] == 1]
best_combinations = df_positive_feedback.sort_values(
    by="Composite Score", ascending=False
)

df_positive_feedback = df[df["Qualitative Feedback Binary"] == 1]

# df_without_study = df[df["Prompt Type"] != "study"]

average_scores = df.groupby(["Prompt Type", "Length Limit", "Hunk Size"])[
    "Composite Score"
].mean()

average_scores = average_scores.reset_index()

best_combinations_overall = average_scores.sort_values(
    by="Composite Score", ascending=False
).head(5)

print("Top 5 combinations (without study prompt):\n")
print(best_combinations_overall)

plt.figure(figsize=(8, 6))
sns.barplot(x="Prompt Type", y="Composite Score", data=best_combinations)
plt.title("Composite Score by Prompt Type (Positive Feedback)")
plt.xticks(rotation=45)

plot_counter = 1
plt.savefig(f"/Users/bmah/Documents/plot_{plot_counter}.png")
plot_counter += 1

plt.show()


def plot_metrics_vs_variable(df, variable):
    global plot_counter
    metrics = ["Precision", "Recall", "F1"]

    plt.figure(figsize=(18, 6))
    for idx, metric in enumerate(metrics):
        plt.subplot(1, 3, idx + 1)
        sns.boxplot(x=variable, y=metric, data=df)
        plt.title(f"{metric} vs {variable}")
        plt.xticks(rotation=45)

    plt.tight_layout()
    plt.savefig(f"/Users/bmah/Documents/plot_{plot_counter}.png")
    plot_counter += 1
    plt.show()


for var in ["Prompt Type", "Length Limit", "Hunk Size"]:
    plot_metrics_vs_variable(df, var)


def plot_qualitative_feedback_vs_variable(df, variable):
    global plot_counter
    feedback_counts = (
        df.groupby([variable, "Qualitative Feedback Binary"]).size().unstack().fillna(0)
    )

    feedback_counts.plot(kind="bar", stacked=False, figsize=(8, 5))
    plt.title(f"Qualitative Feedback (YES/NO) vs {variable}")
    plt.ylabel("Count")
    plt.xticks(rotation=45)
    plt.legend(title="Qualitative Feedback", labels=["NO", "YES"])
    plt.savefig(f"/Users/bmah/Documents/plot_{plot_counter}.png")
    plot_counter += 1
    plt.show()


for var in ["Prompt Type", "Length Limit", "Hunk Size"]:
    plot_qualitative_feedback_vs_variable(df, var)

correlation_matrix = df[
    ["Precision", "Recall", "F1", "Qualitative Feedback Binary"]
].corr()

plt.figure(figsize=(8, 6))
sns.heatmap(correlation_matrix, annot=True, cmap="coolwarm", vmin=-1, vmax=1)
plt.title("Correlation Matrix of Metrics and Qualitative Feedback")
plt.savefig(f"/Users/bmah/Documents/plot_{plot_counter}.png")
plot_counter += 1
plt.show()

plt.figure(figsize=(8, 6))
sns.boxplot(x="Qualitative Feedback Binary", y="Comment Length", data=df)
plt.title("Comment Length vs Qualitative Feedback (YES/NO)")
plt.xlabel("Qualitative Feedback Binary (0 = NO, 1 = YES)")
plt.ylabel("Comment Length")
plt.savefig(f"/Users/bmah/Documents/plot_{plot_counter}.png")
plot_counter += 1
plt.show()
