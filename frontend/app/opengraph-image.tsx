import { ImageResponse } from 'next/og';

export const alt = 'Listnara — Evidence-backed Amazon listing audits';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OpenGraphImage() {
  return new ImageResponse(<div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: '76px', background: '#f6f4ee', color: '#0f172a', fontFamily: 'Arial, sans-serif' }}><div style={{ display: 'flex', alignItems: 'center', color: '#065f46', fontSize: 34, fontWeight: 700 }}>Listnara</div><div style={{ display: 'flex', flexDirection: 'column' }}><div style={{ fontSize: 72, lineHeight: 1.05, fontWeight: 700, letterSpacing: '-3px', maxWidth: 1000 }}>Find what your Amazon listing fails to explain.</div><div style={{ marginTop: 30, fontSize: 30, color: '#475569' }}>Evidence. Reasoning. Action.</div></div></div>, size);
}
