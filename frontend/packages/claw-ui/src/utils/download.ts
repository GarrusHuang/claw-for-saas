/**
 * 文件下载 & 剪贴板工具函数。
 */

export function downloadAsFile(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadFromUrl(
  url: string,
  filename: string,
  headers?: Record<string, string>,
  onError?: (err: Error) => void,
) {
  fetch(url, headers ? { headers } : undefined)
    .then((res) => {
      if (!res.ok) throw new Error(`下载失败: HTTP ${res.status}`);
      return res.blob();
    })
    .then((blob) => {
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(blobUrl);
    })
    .catch((err) => {
      console.error('Download error:', err);
      if (onError) onError(err);
    });
}

export function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
}
