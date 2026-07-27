import { getReport } from "../../utils/api";

Page({
  data: {
    loading: true,
    error: "",
    report: null as Record<string, any> | null
  },

  async onLoad(options: Record<string, string | undefined>) {
    const reportId = options.reportId;
    if (!reportId) {
      this.setData({ loading: false, error: "缺少报告标识" });
      return;
    }
    try {
      const response = await getReport(reportId);
      this.setData({ loading: false, report: response.report });
    } catch (error) {
      this.setData({ loading: false, error: error instanceof Error ? error.message : "报告读取失败" });
    }
  }
});
