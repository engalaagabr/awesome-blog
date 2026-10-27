export function getErrorMessage(error) {
    if (typeof error?.detail === "string") {
        return error.detail;
    }
    if (Array.isArray(error?.detail)) {
        return error.detail.map((issue) => {
            const field = (issue.loc || []).filter((part) => part !== "body").join(".");
            return field ? `${field}: ${issue.msg}` : issue.msg;
        }).join("\n");
    }
    return "Something went wrong. Please try again.";
}

export function showModal(id) {
    bootstrap.Modal.getOrCreateInstance(document.getElementById(id)).show();
}

// Bootstrap finishes hiding asynchronously. Wait before opening another modal.
export function hideModal(id) {
    const element = document.getElementById(id);
    const modal = bootstrap.Modal.getInstance(element);
    if (!modal || !element.classList.contains("show")) {
        return Promise.resolve();
    }
    return new Promise((resolve) => {
        element.addEventListener("hidden.bs.modal", resolve, { once: true });
        modal.hide();
    });
}
