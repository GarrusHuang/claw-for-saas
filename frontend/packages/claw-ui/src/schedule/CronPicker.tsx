import { useState, useEffect, useCallback } from 'react';
import { Select, TimePicker, Input } from 'antd';
import dayjs from 'dayjs';

type Frequency = 'daily' | 'weekday' | 'weekly' | 'monthly';

interface CronPickerProps {
  value?: string;
  onChange: (cron: string) => void;
}

const WEEKDAY_OPTIONS = [
  { label: '周一', value: '1' },
  { label: '周二', value: '2' },
  { label: '周三', value: '3' },
  { label: '周四', value: '4' },
  { label: '周五', value: '5' },
  { label: '周六', value: '6' },
  { label: '周日', value: '0' },
];

const DAY_OPTIONS = Array.from({ length: 31 }, (_, i) => ({
  label: `${i + 1} 日`,
  value: String(i + 1),
}));

/** Parse a cron string into frequency/dow/dom/hour/min. Returns null if unrecognizable. */
function parseCron(cron: string): { freq: Frequency; dow: string; dom: string; hour: number; min: number } | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minS, hourS, domS, , dowS] = parts;
  const hour = Number(hourS);
  const min = Number(minS);
  if (isNaN(hour) || isNaN(min)) return null;

  if (dowS === '*' && domS === '*') return { freq: 'daily', dow: '1', dom: '1', hour, min };
  if (dowS === '1-5' && domS === '*') return { freq: 'weekday', dow: '1', dom: '1', hour, min };
  if (dowS !== '*' && domS === '*') return { freq: 'weekly', dow: dowS, dom: '1', hour, min };
  if (dowS === '*' && domS !== '*') return { freq: 'monthly', dow: '1', dom: domS, hour, min };
  return null;
}

function buildCron(freq: Frequency, dow: string, dom: string, hour: number, min: number): string {
  switch (freq) {
    case 'daily':   return `${min} ${hour} * * *`;
    case 'weekday': return `${min} ${hour} * * 1-5`;
    case 'weekly':  return `${min} ${hour} * * ${dow}`;
    case 'monthly': return `${min} ${hour} ${dom} * *`;
  }
}

export default function CronPicker({ value, onChange }: CronPickerProps) {
  const parsed = value ? parseCron(value) : null;
  const [fallbackMode, setFallbackMode] = useState(!value ? false : !parsed);

  const [freq, setFreq] = useState<Frequency>(parsed?.freq ?? 'daily');
  const [dow, setDow] = useState(parsed?.dow ?? '1');
  const [dom, setDom] = useState(parsed?.dom ?? '1');
  const [hour, setHour] = useState(parsed?.hour ?? 9);
  const [min, setMin] = useState(parsed?.min ?? 0);
  const [rawCron, setRawCron] = useState(value ?? '');

  // When value changes externally, try to sync
  useEffect(() => {
    if (!value) return;
    const p = parseCron(value);
    if (p) {
      setFreq(p.freq);
      setDow(p.dow);
      setDom(p.dom);
      setHour(p.hour);
      setMin(p.min);
      setFallbackMode(false);
    } else {
      setRawCron(value);
      setFallbackMode(true);
    }
  }, [value]);

  const emitChange = useCallback((f: Frequency, d: string, dm: string, h: number, m: number) => {
    onChange(buildCron(f, d, dm, h, m));
  }, [onChange]);

  if (fallbackMode) {
    return (
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Input
          value={rawCron}
          onChange={(e) => setRawCron(e.target.value)}
          onBlur={() => onChange(rawCron)}
          placeholder="Cron 表达式 (例: 0 9 * * *)"
          style={{ flex: 1 }}
        />
        <span role="button" tabIndex={0} style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#1677ff', cursor: 'pointer' }} onClick={() => { setFallbackMode(false); emitChange(freq, dow, dom, hour, min); }} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFallbackMode(false); emitChange(freq, dow, dom, hour, min); } }}>
          可视化
        </span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <Select
        value={freq}
        onChange={(v) => { setFreq(v); emitChange(v, dow, dom, hour, min); }}
        style={{ width: 110 }}
        options={[
          { label: '每天', value: 'daily' },
          { label: '工作日', value: 'weekday' },
          { label: '每周', value: 'weekly' },
          { label: '每月', value: 'monthly' },
        ]}
      />
      {freq === 'weekly' && (
        <Select
          value={dow}
          onChange={(v) => { setDow(v); emitChange(freq, v, dom, hour, min); }}
          style={{ width: 90 }}
          options={WEEKDAY_OPTIONS}
        />
      )}
      {freq === 'monthly' && (
        <Select
          value={dom}
          onChange={(v) => { setDom(v); emitChange(freq, dow, v, hour, min); }}
          style={{ width: 90 }}
          options={DAY_OPTIONS}
        />
      )}
      <TimePicker
        value={dayjs().hour(hour).minute(min)}
        format="HH:mm"
        onChange={(t) => {
          if (!t) return;
          const h = t.hour();
          const m = t.minute();
          setHour(h);
          setMin(m);
          emitChange(freq, dow, dom, h, m);
        }}
        style={{ width: 100 }}
        allowClear={false}
      />
      <span role="button" tabIndex={0} style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#1677ff', cursor: 'pointer' }} onClick={() => { setFallbackMode(true); setRawCron(buildCron(freq, dow, dom, hour, min)); }} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFallbackMode(true); setRawCron(buildCron(freq, dow, dom, hour, min)); } }}>
        手动输入
      </span>
    </div>
  );
}
