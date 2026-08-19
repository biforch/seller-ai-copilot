'use client';

import { Copy, Check } from 'lucide-react';
import { useState } from 'react';

import type { ListingResult } from '@/types';
import { ScoreCard } from './ScoreCard';

interface ListingResultProps {
  result: ListingResult;
}

function CopyButton({
  text,
  id,
  copied,
  onCopy,
}: {
  text: string;
  id: string;
  copied: string | null;
  onCopy: (text: string, id: string) => void;
}) {
  return (
    <button
      onClick={() => onCopy(text, id)}
      className="p-1 text-gray-400 hover:text-gray-600"
      title="Copy"
    >
      {copied === id ? (
        <Check className="w-4 h-4 text-green-500" />
      ) : (
        <Copy className="w-4 h-4" />
      )}
    </button>
  );
}

export function ListingResultView({ result }: ListingResultProps) {
  const [copied, setCopied] = useState<string | null>(null);

  const copyToClipboard = async (text: string, key: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div className="space-y-6">
      {result.score && <ScoreCard score={result.score} />}

      <div className="bg-white rounded-xl border p-6">
        <div className="flex items-start justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-500">Title</h3>
          <CopyButton
            text={result.title}
            id="title"
            copied={copied}
            onCopy={copyToClipboard}
          />
        </div>
        <p className="text-lg font-semibold text-gray-900">{result.title}</p>
      </div>

      <div className="bg-white rounded-xl border p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">Bullet Points</h3>
        <ul className="space-y-2">
          {result.bullets.map((bullet, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="text-blue-600 mt-1">•</span>
              <span className="flex-1 text-gray-800">{bullet}</span>
              <CopyButton
                text={bullet}
                id={`bullet-${i}`}
                copied={copied}
                onCopy={copyToClipboard}
              />
            </li>
          ))}
        </ul>
      </div>

      <div className="bg-white rounded-xl border p-6">
        <div className="flex items-start justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-500">Description</h3>
          <CopyButton
            text={result.description}
            id="description"
            copied={copied}
            onCopy={copyToClipboard}
          />
        </div>
        <p className="text-sm text-gray-800 whitespace-pre-wrap break-words">
          {result.description}
        </p>
      </div>

      <div className="bg-white rounded-xl border p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">Keywords</h3>
        <div className="flex flex-wrap gap-2">
          {result.keywords.map((kw, i) => (
            <span
              key={i}
              className="px-3 py-1 bg-blue-50 text-blue-700 text-sm rounded-full"
            >
              {kw}
            </span>
          ))}
        </div>
      </div>

      <p className="text-xs text-gray-400 text-right">
        Tokens used: {result.tokens_used}
      </p>
    </div>
  );
}
