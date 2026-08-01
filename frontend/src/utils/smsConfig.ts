/**
 * Teltonika setparam SMS helpers — copy-paste only; PREDICT does not send SMS.
 */
import type { DeviceType } from '../types';

export const TRACKER_PORT = 5123;
export const HOST_PLACEHOLDER = '<VPS_STATIC_IP>';

export function trackerServerHost(): string {
  return (import.meta.env.VITE_TRACKER_SERVER || '').trim();
}

/** Host used in templates — real IP from env, or a visible placeholder. */
export function templateHost(): string {
  return trackerServerHost() || HOST_PLACEHOLDER;
}

export function primaryServerSms(host: string, apn = 'YOUR_APN'): string {
  // Two leading spaces required when device has no SMS login/password.
  return `  setparam 2001:${apn};2002:;2003:;2004:${host};2005:${TRACKER_PORT};2006:0`;
}

/** FMC001 second server in Duplicate mode (keep existing primary platform). */
export function secondServerDuplicateSms(host: string): string {
  return `  setparam 2010:2;2007:${host};2008:${TRACKER_PORT};2009:0`;
}

export function fmc001SecondServerNote(host: string): string {
  return (
    `FMC001 already on another platform: prefer Second Server Duplicate SMS, ` +
    `or in Configurator set GPRS → Second Server → Mode Duplicate, ` +
    `Domain+Port = ${host}:${TRACKER_PORT}, Protocol TCP.`
  );
}

export type SmsTemplate = {
  id: string;
  title: string;
  body: string;
  hint: string;
};

export function smsTemplates(host: string = templateHost()): SmsTemplate[] {
  return [
    {
      id: 'fmc001-dup',
      title: 'FMC001 — Second server (Duplicate)',
      body: secondServerDuplicateSms(host),
      hint: 'Keeps the current platform. Send to the device SIM. Two leading spaces required if no SMS login/password.',
    },
    {
      id: 'primary',
      title: 'FMC150 / FMC001 — Primary server',
      body: primaryServerSms(host),
      hint: 'Points the main server at PREDICT. Replace YOUR_APN with the SIM operator APN (or leave blank if Auto APN works).',
    },
  ];
}

export function smsGuidance(deviceType: DeviceType, host: string): {
  title: string;
  body: string;
  note: string;
} {
  const h = host || HOST_PLACEHOLDER;
  if (deviceType === 'fmc150') {
    return {
      title: 'Primary server SMS (FMC150)',
      body: primaryServerSms(h),
      note: 'Send this SMS from your phone to the device SIM. PREDICT does not send SMS.',
    };
  }
  return {
    title: 'FMC001 — Second server (Duplicate)',
    body: secondServerDuplicateSms(h),
    note:
      fmc001SecondServerNote(h) +
      ' For full take-over, use the primary-server template instead. PREDICT does not send SMS.',
  };
}
