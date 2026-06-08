import type { OnboardingCheckStatus } from "../../api";

export const statusLabel: Record<OnboardingCheckStatus, string> = {
  ok: "正常",
  warning: "注意",
  error: "阻塞",
  skipped: "跳过"
};

export function statusTone(status: OnboardingCheckStatus) {
  return `onboarding-status-${status}`;
}

export async function copyText(value: string) {
  if (!value) return;
  await navigator.clipboard?.writeText(value);
}
