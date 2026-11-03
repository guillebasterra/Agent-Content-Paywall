/** Carries a file dropped on the dashboard over to /upload. It survives client navigation only, and a reload clears it. */
let pending: File | null = null;

export function setPendingUpload(file: File) {
  pending = file;
}

export function takePendingUpload(): File | null {
  const file = pending;
  pending = null;
  return file;
}
