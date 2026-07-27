import { Clarification, createConversation, getTask, submitMessage } from "../../utils/api";

interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
}

Page({
  data: {
    conversationId: "",
    draft: "",
    messages: [] as DisplayMessage[],
    clarifications: [] as Clarification[],
    taskStatus: "",
    submitting: false
  },

  async onShow() {
    if (!this.data.conversationId) {
      await this.createConversation();
    }
  },

  onInput(event: WechatMiniprogram.Input) {
    this.setData({ draft: event.detail.value });
  },

  async onSubmit() {
    const content = this.data.draft.trim();
    if (!content || this.data.submitting) {
      return;
    }
    this.setData({
      submitting: true,
      draft: "",
      clarifications: [],
      messages: [...this.data.messages, { role: "user", content }]
    });
    try {
      const submission = await submitMessage(this.data.conversationId, content);
      const messages = submission.assistant_message
        ? [...this.data.messages, { role: "assistant" as const, content: submission.assistant_message }]
        : this.data.messages;
      this.setData({ messages, clarifications: submission.intent.clarifications });
      if (submission.task_id) {
        await this.pollTask(submission.task_id);
      }
    } catch (error) {
      this.setData({
        messages: [...this.data.messages, { role: "assistant", content: `请求未完成：${messageOf(error)}` }]
      });
    } finally {
      this.setData({ submitting: false });
    }
  },

  async createConversation() {
    try {
      const conversation = await createConversation();
      this.setData({ conversationId: conversation.id });
    } catch (error) {
      wx.showToast({ title: `登录或服务不可用：${messageOf(error)}`, icon: "none" });
    }
  },

  async pollTask(taskId: string) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const task = await getTask(taskId);
      this.setData({ taskStatus: task.status });
      if (task.status === "completed" && task.report_id) {
        wx.navigateTo({ url: `/pages/report/index?reportId=${encodeURIComponent(task.report_id)}` });
        return;
      }
      if (task.status === "failed") {
        this.setData({
          messages: [...this.data.messages, { role: "assistant", content: task.safe_error || "研究任务未完成" }]
        });
        return;
      }
      await delay(1500);
    }
    this.setData({
      messages: [...this.data.messages, { role: "assistant", content: "任务仍在处理中，请稍后查看历史记录。" }]
    });
  }
});

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "未知错误";
}
