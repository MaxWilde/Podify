import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { addTracksUpload, type AddTracksResult } from "../api/tracks";
import { useMountpointStore } from "../store/mountpoint";
import { useToastStore, toastErrorMessage } from "../store/toast";
import { useInvalidateLibrary } from "../hooks/useLibraryMutations";

export function UploadPage() {
  const connectedMountpoint = useMountpointStore((s) => s.connectedMountpoint);
  const push = useToastStore((s) => s.push);
  const invalidate = useInvalidateLibrary();
  const [dragActive, setDragActive] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [lastResult, setLastResult] = useState<AddTracksResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadMutation = useMutation({
    mutationFn: (files: File[]) => addTracksUpload(connectedMountpoint as string, files),
    onSuccess: (result) => {
      push(result.message, "success");
      setLastResult(result);
      setPendingFiles([]);
      invalidate();
    },
    onError: (error) => push(toastErrorMessage(error), "error"),
  });

  function addFiles(fileList: FileList | null) {
    if (!fileList) return;
    setPendingFiles((prev) => [...prev, ...Array.from(fileList)]);
  }

  function handleUpload() {
    if (!connectedMountpoint) {
      push("Connect to an iPod before uploading.", "error");
      return;
    }
    if (pendingFiles.length === 0) return;
    uploadMutation.mutate(pendingFiles);
  }

  return (
    <div className="pt-4">
      <h1 className="mb-4 text-2xl font-bold">Upload</h1>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`flex h-48 cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed text-center transition-colors ${
          dragActive ? "border-accent bg-surface" : "border-border bg-surface/50"
        }`}
      >
        <p className="text-text">Drag and drop audio files here</p>
        <p className="text-sm text-text-secondary">or click to browse</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".mp3,.m4a,.aac,.wav,.aiff,.aif,.flac,.ogg,.opus,.m4b"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {pendingFiles.length > 0 && (
        <div className="mt-4 rounded-md bg-surface p-3">
          <div className="mb-2 text-sm font-semibold text-text-secondary">
            {pendingFiles.length} file(s) ready
          </div>
          <ul className="mb-3 max-h-40 space-y-1 overflow-y-auto text-sm text-text-secondary">
            {pendingFiles.map((file, index) => (
              <li key={`${file.name}-${index}`} className="flex items-center justify-between">
                <span className="truncate">{file.name}</span>
                <button
                  onClick={() => setPendingFiles((prev) => prev.filter((_, i) => i !== index))}
                  className="ml-2 text-text-secondary hover:text-red-400"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button
              onClick={handleUpload}
              disabled={uploadMutation.isPending}
              className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-black hover:opacity-90 disabled:opacity-50"
            >
              {uploadMutation.isPending ? "Uploading..." : "Add to iPod"}
            </button>
            <button
              onClick={() => setPendingFiles([])}
              className="rounded bg-surface-hover px-4 py-1.5 text-sm text-text hover:bg-neutral-700"
            >
              Clear
            </button>
          </div>
        </div>
      )}

      {lastResult && (
        <div className="mt-4 rounded-md bg-surface p-3 text-sm text-text-secondary">
          <div>Added: {lastResult.added_count}</div>
          <div>Converted (FLAC→ALAC): {lastResult.converted_count}</div>
          {lastResult.conversion_failed_count > 0 && (
            <div className="text-yellow-400">Conversion failed: {lastResult.conversion_failed_count}</div>
          )}
          {lastResult.skipped_count > 0 && <div>Skipped (unsupported): {lastResult.skipped_count}</div>}
        </div>
      )}
    </div>
  );
}
