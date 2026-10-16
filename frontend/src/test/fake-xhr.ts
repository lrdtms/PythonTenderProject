type ProgressEvent = { lengthComputable: boolean; loaded: number; total: number };

export class FakeXhr {
  static instances: FakeXhr[] = [];
  static get last(): FakeXhr {
    return FakeXhr.instances[FakeXhr.instances.length - 1];
  }
  headers: Record<string, string> = {};
  upload: { onprogress?: (e: ProgressEvent) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  ontimeout?: () => void;
  status = 0;
  responseText = "";
  method = "";
  url = "";
  body: unknown;
  constructor() {
    FakeXhr.instances.push(this);
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
  }
  abort() {
    this.onabort?.();
  }
  /** Test helpers */
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
}
