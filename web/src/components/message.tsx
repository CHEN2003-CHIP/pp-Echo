import { memo, type ComponentProps, type HTMLAttributes, type ReactNode } from "react";
import { Check, Copy, RefreshCw } from "lucide-react";
import { cjk } from "@streamdown/cjk";
import { code } from "@streamdown/code";
import { math } from "@streamdown/math";
import { mermaid } from "@streamdown/mermaid";
import { Streamdown } from "streamdown";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type MessageRole = "user" | "assistant" | "system" | "tool" | "activity" | "error" | string;

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
  from: MessageRole;
  streaming?: boolean;
};

export function Message({ className, from, streaming = false, ...props }: MessageProps) {
  return <div className={cn("pp-message", `pp-message-${from}`, streaming && "pp-message-streaming", className)} {...props} />;
}

export type MessageContentProps = HTMLAttributes<HTMLDivElement> & {
  from?: MessageRole;
};

export function MessageContent({ className, from, ...props }: MessageContentProps) {
  return <div className={cn("pp-message-content", from && `pp-message-content-${from}`, className)} {...props} />;
}

export type MessageResponseProps = Omit<ComponentProps<typeof Streamdown>, "plugins"> & {
  streaming?: boolean;
};

const streamdownPlugins = { cjk, code, math, mermaid };

export const MessageResponse = memo(
  ({ className, children, streaming = false, ...props }: MessageResponseProps) => (
    <div className={cn("pp-message-response", className)}>
      <Streamdown plugins={streamdownPlugins} {...props}>
        {children}
      </Streamdown>
      {streaming ? <span className="stream-cursor markdown-cursor" aria-hidden="true" /> : null}
    </div>
  ),
  (prevProps, nextProps) => prevProps.children === nextProps.children && prevProps.streaming === nextProps.streaming,
);

MessageResponse.displayName = "MessageResponse";

export type MessageToolbarProps = HTMLAttributes<HTMLDivElement>;

export function MessageToolbar({ className, ...props }: MessageToolbarProps) {
  return <div className={cn("pp-message-toolbar", className)} {...props} />;
}

export type MessageActionProps = ComponentProps<typeof Button> & {
  label: string;
};

export function MessageAction({ className, label, children, variant = "ghost", size = "icon", ...props }: MessageActionProps) {
  return (
    <Button className={cn("pp-message-action", className)} title={label} aria-label={label} variant={variant} size={size} type="button" {...props}>
      {children}
    </Button>
  );
}

export function DefaultAssistantActions({
  text,
  copied,
  onCopy,
  onRetry,
}: {
  text: string;
  copied?: boolean;
  onCopy?: (text: string) => void;
  onRetry?: () => void;
}) {
  const hasText = text.trim().length > 0;
  if (!hasText && !onRetry) return null;
  return (
    <MessageToolbar>
      <div className="pp-message-toolbar-group">
        {hasText ? (
          <MessageAction label={copied ? "Copied" : "Copy"} onClick={() => onCopy?.(text)}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </MessageAction>
        ) : null}
        {onRetry ? (
          <MessageAction label="Regenerate" onClick={onRetry}>
            <RefreshCw size={14} />
          </MessageAction>
        ) : null}
      </div>
    </MessageToolbar>
  );
}

export function MessagePlainText({ children }: { children: ReactNode }) {
  return <div className="pp-message-plain">{children}</div>;
}
