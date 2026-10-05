/** Save (or open, for PDFs) a blob answered by an export / payslip route. */
export const downloadBlob = (blob: Blob, filename: string, open = false) => {
  const url = URL.createObjectURL(blob);
  if (open) {
    window.open(url, '_blank', 'noopener');
  } else {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
};
