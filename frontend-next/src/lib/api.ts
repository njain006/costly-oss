import axios from "axios";
import { getSfAccount, withSfAccount } from "@/lib/sf-account";

const api = axios.create({
  baseURL: "/api",
});

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    // In demo mode, rewrite data URLs to /api/demo/...
    // Never rewrite auth endpoints — login/register/refresh must always hit the real API
    if (localStorage.getItem("costly_demo") === "1") {
      const url = config.url || "";
      const isAuthUrl = url.startsWith("/auth");
      if (!isAuthUrl && !url.startsWith("/demo")) {
        config.url = `/demo${url}`;
        return config;
      }
    }

    // Every Snowflake request, reads and writes alike (resize, auto-suspend,
    // query sync, chat), targets the account picked in the sidebar.
    // withSfAccount leaves non-Snowflake paths and explicit ids alone.
    if (config.url) config.url = withSfAccount(config.url, getSfAccount());

    const token = localStorage.getItem("costly_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    const originalRequest = error.config;

    // Don't attempt refresh in demo mode
    if (typeof window !== "undefined" && localStorage.getItem("costly_demo") === "1") {
      return Promise.reject(
        error.response?.data?.detail || error.message || "Request failed"
      );
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      if (typeof window !== "undefined") {
        const refreshToken = localStorage.getItem("costly_refresh_token");
        if (refreshToken) {
          try {
            const res = await axios.post(
              `${api.defaults.baseURL}/auth/refresh`,
              { refresh_token: refreshToken }
            );
            const { token, refresh_token: newRefresh, user_id, name, email, role } = res.data;
            localStorage.setItem("costly_token", token);
            localStorage.setItem("costly_refresh_token", newRefresh);
            if (user_id) {
              localStorage.setItem("costly_user", JSON.stringify({ user_id, name, email, role }));
            }
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          } catch {
            localStorage.removeItem("costly_token");
            localStorage.removeItem("costly_refresh_token");
            localStorage.removeItem("costly_user");
            window.location.href = "/login";
          }
        } else {
          localStorage.removeItem("costly_token");
          localStorage.removeItem("costly_user");
          window.location.href = "/login";
        }
      }
    }

    // Connector errors come as {error: {vendor_message, remediation_hint}};
    // show what happened and what to do, not a generic failure.
    const env = error.response?.data?.error;
    const connectorMsg = env
      ? [env.vendor_message || env.message, env.remediation_hint].filter(Boolean).join(" ")
      : null;
    return Promise.reject(
      connectorMsg || error.response?.data?.detail || error.message || "Request failed"
    );
  }
);

export default api;
