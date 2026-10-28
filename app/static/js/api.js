import { getErrorMessage } from "./utils.js?v=3";

export function createApi(homeUrl, onUnauthorized) {
    let refreshing = null;
    let sessionVersion = 0;
    const authPaths = new Set(["users/login", "users/register", "users/refresh", "users/logout"]);

    async function request(path, { method = "GET", body } = {}) {
        const isForm = body instanceof FormData;
        try {
            return await fetch(new URL(`api/${path}`, homeUrl), {
                method,
                credentials: "same-origin",
                cache: "no-store",
                headers: body === undefined || isForm ? {} : { "Content-Type": "application/json" },
                body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
            });
        } catch {
            throw new Error("Unable to reach the server. Please check your connection and try again.");
        }
    }

    async function renewSession() {
        // Another tab may have renewed the shared cookies while this tab waited.
        const renew = async () => {
            const profile = await request("users/me");
            if (profile.ok) return true;
            if (profile.status !== 401) {
                throw new Error("Unable to renew your session. Please try again.");
            }
            const response = await request("users/refresh", { method: "POST" });
            if (response.ok) return true;
            if (response.status !== 401) {
                throw new Error("Unable to renew your session. Please try again.");
            }
            return false;
        };
        // Web Locks coordinate refresh rotation with other tabs on supported browsers.
        const renewed = globalThis.navigator?.locks
            ? await navigator.locks.request("blog-session-refresh", renew)
            : await renew();
        if (renewed) sessionVersion += 1;
        return renewed;
    }

    return async function api(path, options = {}) {
        const version = sessionVersion;
        let response = await request(path, options);
        if (response.status === 401 && !authPaths.has(path)) {
            if (version !== sessionVersion) {
                response = await request(path, options);
            } else {
                if (!refreshing) refreshing = renewSession().finally(() => { refreshing = null; });
                if (await refreshing) response = await request(path, options);
            }
        }
        if (response.status === 204) return null;
        const data = await response.json().catch(() => null);
        if (!response.ok) {
            if (response.status === 401 && path !== "users/login") onUnauthorized();
            const error = new Error(getErrorMessage(data));
            error.status = response.status;
            throw error;
        }
        return data;
    };
}
