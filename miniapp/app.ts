import { ensureSession } from "./utils/api";

App({
  async onLaunch() {
    try {
      await ensureSession();
    } catch (_error) {
      // The research screen presents a retryable message.  Never fall back to
      // a hard-coded identity when WeChat login is not configured.
    }
  }
});
