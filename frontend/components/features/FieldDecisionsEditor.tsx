'use client';

import {
  LISTING_DECISION_FIELDS,
  type ListingDecisionField,
} from '@/lib/listing-proposals';
import type { FieldDecisions, FieldDecisionValue } from '@/types';

const FIELD_LABELS: Record<ListingDecisionField, string> = {
  title: 'Title',
  bullets: 'Bullets',
  description: 'Description',
  backend_keywords: 'Backend Keywords',
};

interface FieldDecisionsEditorProps {
  decisions: FieldDecisions;
  readonly?: boolean;
  onChange: (field: ListingDecisionField, value: FieldDecisionValue) => void;
}

function DecisionOption({
  name,
  value,
  checked,
  disabled,
  onChange,
  label,
}: {
  name: string;
  value: FieldDecisionValue;
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-gray-700">
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="text-blue-600 focus:ring-blue-500"
      />
      {label}
    </label>
  );
}

export function FieldDecisionsEditor({
  decisions,
  readonly = false,
  onChange,
}: FieldDecisionsEditorProps) {
  return (
    <section className="rounded-xl border bg-white p-6 space-y-5">
      <div>
        <h3 className="text-sm font-medium text-gray-500">Field Decisions</h3>
        <p className="text-sm text-gray-500 mt-1">
          Choose Accept or Reject for each listing field before approving.
        </p>
      </div>

      {LISTING_DECISION_FIELDS.map((field) => {
        const value = decisions[field];
        const pending = value === 'pending';
        return (
          <fieldset key={field} className="rounded-lg border p-4">
            <legend className="px-1 text-sm font-medium text-gray-900">
              {FIELD_LABELS[field]}
              {pending && (
                <span className="ml-2 text-xs font-normal text-amber-700">Pending</span>
              )}
            </legend>
            <div className="mt-3 flex flex-wrap gap-4">
              <DecisionOption
                name={`decision-${field}`}
                value="accept"
                checked={value === 'accept'}
                disabled={readonly}
                onChange={() => onChange(field, 'accept')}
                label="Accept"
              />
              <DecisionOption
                name={`decision-${field}`}
                value="reject"
                checked={value === 'reject'}
                disabled={readonly}
                onChange={() => onChange(field, 'reject')}
                label="Reject"
              />
            </div>
          </fieldset>
        );
      })}
    </section>
  );
}
