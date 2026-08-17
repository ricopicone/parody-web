/**
 * Printing.
 *
 * The viewer is a scrolling stack of canvases, and only the pages near the
 * viewport hold one — so printing the DOM gives blank sheets for everything
 * the reader has not scrolled past. Worse, in dark mode the page canvas
 * carries an inversion filter, and a browser will happily print that.
 *
 * So we do not print the DOM. We print the PDF the server composites, which
 * has every page, the reader's ink drawn in, vector text, and light paper by
 * construction. A hidden same-origin iframe holds it and prints itself.
 */

/**
 * Where to print from: the annotated copy when there is ink, else the plain PDF.
 *
 * Always asks for it inline. The download endpoints send
 * `Content-Disposition: attachment`, and pointing an iframe at an attachment
 * downloads the file instead of rendering it — so "Print" quietly saved a copy
 * and no dialog ever appeared. There is nothing to print until the document is
 * actually in the frame.
 */
export function printUrl(root) {
  const url = root.dataset.downloadUrl || root.dataset.pdfUrl;
  if (!url) return url;
  return url + (url.includes('?') ? '&' : '?') + 'inline=1';
}

/**
 * Print, resolving to false when the browser would not do it in an iframe
 * (Safari is unreliable here) so the caller can fall back to opening the file.
 */
export function printPdf(url, { timeout = 8000 } = {}) {
  return new Promise((resolve) => {
    const frame = document.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;';
    let settled = false;
    const done = (ok) => {
      if (settled) return;
      settled = true;
      // Leave the frame alive briefly: removing it while the print dialog is
      // open cancels the job in some browsers.
      setTimeout(() => frame.remove(), 60000);
      resolve(ok);
    };
    const giveUp = setTimeout(() => done(false), timeout);
    frame.onload = () => {
      clearTimeout(giveUp);
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
        done(true);
      } catch (err) {
        done(false);
      }
    };
    frame.onerror = () => { clearTimeout(giveUp); done(false); };
    frame.src = url;
    document.body.appendChild(frame);
  });
}

/**
 * Take over printing for this page.
 *
 * ⌘P/Ctrl-P is intercepted, which is how most people print. The browser's own
 * File > Print menu cannot be intercepted at all, which is what the print
 * stylesheet is for.
 */
export function bindPrint(root) {
  const print = async () => {
    const url = printUrl(root);
    if (!url) return;
    if (!await printPdf(url)) window.open(url, '_blank', 'noopener');
  };
  window.addEventListener('keydown', (event) => {
    if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'p') return;
    event.preventDefault();
    print();
  });
  return print;
}
