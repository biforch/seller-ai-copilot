'use client';

import { TrendingDown, TrendingUp, Lightbulb } from 'lucide-react';

import type { AnalyzeResult } from '@/types';

interface AnalyzerResultProps {
  result: AnalyzeResult;
}

export function AnalyzerResultView({ result }: AnalyzerResultProps) {
  const sections = [
    {
      title: 'Strengths',
      items: result.strengths,
      icon: TrendingUp,
      color: 'text-green-600',
      bg: 'bg-green-50',
    },
    {
      title: 'Weaknesses',
      items: result.weaknesses,
      icon: TrendingDown,
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
    {
      title: 'Opportunities',
      items: result.opportunities,
      icon: Lightbulb,
      color: 'text-amber-600',
      bg: 'bg-amber-50',
    },
  ];

  return (
    <div className="grid md:grid-cols-3 gap-4">
      {sections.map(({ title, items, icon: Icon, color, bg }) => (
        <div key={title} className="bg-white rounded-xl border p-6">
          <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full ${bg} mb-4`}>
            <Icon className={`w-4 h-4 ${color}`} />
            <span className={`text-sm font-medium ${color}`}>{title}</span>
          </div>
          <ul className="space-y-2">
            {items.map((item, i) => (
              <li key={i} className="text-sm text-gray-700 flex items-start gap-2">
                <span className={`${color} mt-0.5`}>•</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
