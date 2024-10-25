import matplotlib.pyplot as plt
import pandas as pd

csv_file = "evaluated_code_generations.csv"
data = pd.read_csv(csv_file)

if all(
    col in data.columns
    for col in [
        "Reference Fix",
        "Generated Code Length",
        "Comment Length",
        "Qualitative Feedback",
    ]
):
    data["Reference Fix Length"] = data["Reference Fix"].str.len()

    data["Feedback YES/NO"] = (
        data["Qualitative Feedback"]
        .str.startswith("YES")
        .map({True: "YES", False: "NO"})
    )

    def plot_metrics(column, title_prefix):
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))

        axes[0].scatter(data[column], data["Precision"], color="blue")
        axes[0].set_title(f"Precision by {title_prefix}")
        axes[0].set_xlabel(title_prefix)
        axes[0].set_ylabel("Precision")
        axes[0].grid(True)

        axes[1].scatter(data[column], data["Recall"], color="green")
        axes[1].set_title(f"Recall by {title_prefix}")
        axes[1].set_xlabel(title_prefix)
        axes[1].set_ylabel("Recall")
        axes[1].grid(True)

        axes[2].scatter(data[column], data["F1"], color="red")
        axes[2].set_title(f"F1 by {title_prefix}")
        axes[2].set_xlabel(title_prefix)
        axes[2].set_ylabel("F1")
        axes[2].grid(True)

        plt.tight_layout()
        plt.show()

        fig, ax = plt.subplots(figsize=(10, 6))
        data.boxplot(column=column, by="Feedback YES/NO", ax=ax, grid=False)

        ax.set_title(f"{title_prefix} by Qualitative Feedback (YES/NO)")
        ax.set_xlabel("Qualitative Feedback (YES/NO)")
        ax.set_ylabel(title_prefix)
        plt.suptitle("")
        plt.show()

    plot_metrics("Reference Fix Length", "Reference Fix Length")

    plot_metrics("Generated Code Length", "Generated Code Length")

    plot_metrics("Comment Length", "Comment Length")

    feedback_counts = data["Feedback YES/NO"].value_counts()

    fig, ax = plt.subplots(figsize=(6, 6))
    labels = [
        f"{label} ({count})"
        for label, count in zip(feedback_counts.index, feedback_counts)
    ]
    ax.pie(
        feedback_counts,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        colors=["#66b3ff", "#99ff99"],
    )
    ax.set_title("Distribution of Qualitative Feedback (YES/NO) with Counts")
    plt.show()

else:
    print("One or more of the necessary columns do not exist in the CSV file.")
