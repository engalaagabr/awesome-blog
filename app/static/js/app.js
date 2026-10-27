import { getErrorMessage, hideModal, showModal } from "./utils.js?v=3";

const homeUrl = document.querySelector(".navbar-brand").href;
const pageMessage = document.getElementById("pageMessage");
const postDetail = document.getElementById("postDetail");
let currentUser = null;
let pendingNewPost = false;

function message(text, type = "success") {
    pageMessage.textContent = text;
    pageMessage.className = `alert alert-${type}`;
    pageMessage.hidden = false;
}

function updateUser(user) {
    currentUser = user;
    document.querySelectorAll("[data-auth-only]").forEach(element => {
        element.hidden = !user;
    });
    document.querySelectorAll("[data-guest-only]").forEach(element => {
        element.hidden = Boolean(user);
    });
    document.getElementById("currentUsername").textContent = user?.username || "";
    document.querySelectorAll("[data-my-posts]").forEach(link => {
        if (user) link.href = new URL(`users/${user.id}/posts`, homeUrl).href;
        else link.removeAttribute("href");
    });
    if (postDetail) {
        document.getElementById("postActions").hidden =
            !user || user.id !== Number(postDetail.dataset.authorId);
    }
}

async function api(path, { method = "GET", body } = {}) {
    let response;
    try {
        response = await fetch(new URL(`api/${path}`, homeUrl), {
            method,
            credentials: "same-origin",
            cache: "no-store",
            headers: body === undefined ? {} : { "Content-Type": "application/json" },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
    } catch {
        throw new Error("Unable to reach the server. Please check your connection and try again.");
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
        if (response.status === 401 && path !== "users/login") updateUser(null);
        const error = new Error(getErrorMessage(data));
        error.status = response.status;
        throw error;
    }
    return data;
}

const sessionReady = api("users/me").then(updateUser).catch(error => {
    updateUser(null);
    if (error.status !== 401) message(error.message, "danger");
});

function bindForm(id, action) {
    const form = document.getElementById(id);
    if (!form) return;
    form.addEventListener("submit", async event => {
        event.preventDefault();
        const button = form.querySelector('button[type="submit"]');
        if (button.disabled || !form.reportValidity()) return;
        const errorBox = form.querySelector("[data-form-error]");
        const label = button.textContent;
        errorBox.hidden = true;
        button.disabled = true;
        button.textContent = "Please wait...";
        try {
            await action(Object.fromEntries(new FormData(form)), form);
        } catch (error) {
            errorBox.textContent = error.message;
            errorBox.hidden = false;
        } finally {
            button.disabled = false;
            button.textContent = label;
        }
    });
}

async function success(sourceModal, text, destination) {
    document.getElementById("successMessage").textContent = text;
    if (destination) {
        document.getElementById("successModal").addEventListener("hidden.bs.modal", () => {
            window.location.assign(destination);
        }, { once: true });
    }
    await hideModal(sourceModal);
    showModal("successModal");
}

document.querySelectorAll("[data-new-post]").forEach(button => {
    button.addEventListener("click", async () => {
        await sessionReady;
        if (currentUser) {
            showModal("createPostModal");
        } else {
            pendingNewPost = true;
            const notice = document.getElementById("loginNotice");
            notice.textContent = "Log in to write a post.";
            notice.hidden = false;
            showModal("loginModal");
        }
    });
});

bindForm("registerForm", async (data, form) => {
    if (data.password !== data.confirm_password) throw new Error("Passwords do not match.");
    const user = await api("users/register", {
        method: "POST",
        body: { username: data.username.trim(), email: data.email.trim(), password: data.password },
    });
    form.reset();
    document.getElementById("loginUsername").value = user.username;
    document.getElementById("loginPassword").value = "";
    const notice = document.getElementById("loginNotice");
    notice.textContent = "Account created. Log in to continue.";
    notice.hidden = false;
    await hideModal("registerModal");
    showModal("loginModal");
});

bindForm("loginForm", async (data, form) => {
    await sessionReady;
    const user = await api("users/login", {
        method: "POST", body: { username: data.username.trim(), password: data.password },
    });
    updateUser(user);
    form.reset();
    document.getElementById("loginNotice").hidden = true;
    await hideModal("loginModal");
    message(`Welcome, ${user.username}!`);
    if (pendingNewPost) {
        pendingNewPost = false;
        showModal("createPostModal");
    }
});

document.getElementById("logoutButton").addEventListener("click", async event => {
    const button = event.currentTarget;
    if (button.disabled) return;
    button.disabled = true;
    try {
        await api("users/logout", { method: "POST" });
        updateUser(null);
        pendingNewPost = false;
        document.getElementById("createPostForm").reset();
        message("You have been logged out.");
    } catch (error) {
        message(error.message, "danger");
    } finally {
        button.disabled = false;
    }
});

function postFields(data) {
    const title = data.title.trim();
    const content = data.content.trim();
    if (!title || !content) throw new Error("Please enter a title and content.");
    return { title, content };
}

bindForm("createPostForm", async (data, form) => {
    const post = await api("posts/", { method: "POST", body: postFields(data) });
    form.reset();
    await success("createPostModal", `Post "${post.title}" created successfully!`,
        new URL(`posts/${post.id}`, homeUrl).href);
});

if (postDetail) {
    const postPath = `posts/${postDetail.dataset.postId}`;
    document.getElementById("editPostModal").addEventListener("show.bs.modal", () => {
        document.getElementById("editTitle").value = postDetail.querySelector(".article-title").textContent;
        document.getElementById("editContent").value = postDetail.querySelector(".article-content").textContent;
        document.querySelector("#editPostForm [data-form-error]").hidden = true;
    });
    bindForm("editPostForm", async data => {
        const post = await api(postPath, { method: "PATCH", body: postFields(data) });
        postDetail.querySelector(".article-title").textContent = post.title;
        postDetail.querySelector(".article-content").textContent = post.content;
        document.title = `FastAPI Blog - ${post.title.slice(0, 50)}`;
        await success("editPostModal", "Post updated successfully!");
    });
    bindForm("deletePostForm", async () => {
        await api(postPath, { method: "DELETE" });
        window.location.assign(homeUrl);
    });
}

// Refresh ownership controls if another tab logged in or out.
window.addEventListener("pageshow", event => {
    if (event.persisted) api("users/me").then(updateUser).catch(() => updateUser(null));
});
