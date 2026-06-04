import { useEffect, useState } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";

type Props = {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  /** When set, the user must type this exact text to enable confirm (e.g. "LIVE"). */
  requireText?: string;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  danger,
  requireText,
  onConfirm,
  onCancel,
}: Props) {
  const [text, setText] = useState("");

  useEffect(() => {
    if (!open) setText("");
  }, [open]);

  const ready = !requireText || text === requireText;

  return (
    <Modal open={open} title={title} onClose={onCancel}>
      <p className="text-sm text-slate-300">{message}</p>
      {requireText && (
        <input
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={`Type ${requireText} to confirm`}
          className="mt-3 w-full rounded border border-panelBorder bg-bg px-3 py-2 text-sm outline-none focus:border-sky-500"
        />
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant={danger ? "danger" : "primary"}
          disabled={!ready}
          onClick={onConfirm}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
