'use client';

import type { ListingScore } from '@/types';

interface ScoreCardProps {
  score: ListingScore;
}

const LABELS: Record<keyof Omit<ListingScore, 'overall'>, string> = {
  title_seo: 'Title SEO',
  keyword_coverage: 'Keyword Coverage',
  benefit_clarity: 'Benefit Clarity',
  conversion_potential: 'Conversion Potential',
};

function barColor(value: number) {
  if (value >= 80) return 'bg-green-500';
  if (value >= 60) return 'bg-amber-500';
  return 'bg-red-500';
}

export function ScoreCard({ score }: ScoreCardProps) {
  const breakdownKeys = Object.keys(LABELS) as Array<keyof typeof LABELS>;

  return (
    <div className="bg-white rounded-xl border p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-500">
          Listing Quality Score
        </h3>
        <span className="text-2xl font-bold text-gray-900">
          {score.overall}
          <span className="text-sm font-normal text-gray-400">/100</span>
        </span>
      </div>

      <div className="space-y-3">
        {breakdownKeys.map((key) => (
          <div key={key}>
            <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
              <span>{LABELS[key]}</span>
              <span>{score[key]}</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-2">
              <div
                className={`h-2 rounded-full ${barColor(score[key])}`}
                style={{ width: `${score[key]}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
