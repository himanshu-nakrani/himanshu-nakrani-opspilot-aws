import React from 'react';

// File paths (a/b.py:29), calls (get_order()), exception names, and quoted identifiers.
const TOKEN = /([\w./-]+\.(?:py|ts|tsx|js|json|ya?ml)(?::\d+)?|\b\w+\(\)|\b[A-Z]\w*(?:Error|Exception)\b|'[\w.-]+')/g;

/** Renders free-text summaries with code-ish tokens set in mono. */
export const CodeText: React.FC<{ text: string }> = ({ text }) => {
  const parts = text.split(TOKEN);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <code key={i} className="font-mono text-[12px] text-ink-100">
            {p}
          </code>
        ) : (
          <React.Fragment key={i}>{p}</React.Fragment>
        ),
      )}
    </>
  );
};
