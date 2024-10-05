import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

df = pd.read_csv("metrics_results.csv")

df.fillna(0, inplace=True)

df["Qualitative Feedback Binary"] = df["Qualitative Feedback"].apply(
    lambda x: 1 if x.startswith("YES") else 0
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

print("Top 5 Best Combinations:")
print(
    best_combinations[
        [
            "Prompt Type",
            "Length Limit",
            "Hunk Size",
            "Precision",
            "Recall",
            "F1",
            "Composite Score",
        ]
    ].head()
)

plt.figure(figsize=(8, 6))
sns.barplot(x="Prompt Type", y="Composite Score", data=best_combinations)
plt.title("Composite Score by Prompt Type (Positive Feedback)")
plt.xticks(rotation=45)
plt.show()


def plot_metrics_vs_variable(df, variable):
    metrics = ["Precision", "Recall", "F1"]

    plt.figure(figsize=(18, 6))
    for idx, metric in enumerate(metrics):
        plt.subplot(1, 3, idx + 1)
        sns.boxplot(x=variable, y=metric, data=df)
        plt.title(f"{metric} vs {variable}")
        plt.xticks(rotation=45)

    plt.tight_layout()
    plt.show()


for var in ["Prompt Type", "Length Limit", "Hunk Size"]:
    plot_metrics_vs_variable(df, var)


def plot_qualitative_feedback_vs_variable(df, variable):
    feedback_counts = (
        df.groupby([variable, "Qualitative Feedback Binary"]).size().unstack().fillna(0)
    )

    feedback_counts.plot(kind="bar", stacked=False, figsize=(8, 5))
    plt.title(f"Qualitative Feedback (YES/NO) vs {variable}")
    plt.ylabel("Count")
    plt.xticks(rotation=45)
    plt.legend(title="Qualitative Feedback", labels=["NO", "YES"])
    plt.show()


for var in ["Prompt Type", "Length Limit", "Hunk Size"]:
    plot_qualitative_feedback_vs_variable(df, var)

correlation_matrix = df[
    ["Precision", "Recall", "F1", "Qualitative Feedback Binary"]
].corr()

plt.figure(figsize=(8, 6))
sns.heatmap(correlation_matrix, annot=True, cmap="coolwarm", vmin=-1, vmax=1)
plt.title("Correlation Matrix of Metrics and Qualitative Feedback")
plt.show()
