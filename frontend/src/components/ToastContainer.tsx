import { useToastStore } from "../store/toast";

const VARIANT_STYLES: Record<string, string> = {
  error: "bg-red-600/90 border-red-400",
  success: "bg-emerald-600/90 border-emerald-400",
  info: "bg-neutral-800/95 border-neutral-600",
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          onClick={() => dismiss(toast.id)}
          className={`cursor-pointer rounded-md border px-4 py-3 text-sm text-white shadow-lg ${VARIANT_STYLES[toast.variant]}`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
