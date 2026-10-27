// The AudioContext resamples the microphone to 16 kHz before this worklet.
class VoiceCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const requested = options?.processorOptions?.frameSize;
    this.frameSize = Number.isInteger(requested) && requested >= 512 && requested <= 4000 ? requested : 4000;
    this.samples = new Int16Array(this.frameSize); this.offset = 0;
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) for (const value of input) {
      this.samples[this.offset++] = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
      if (this.offset === this.samples.length) {
        this.port.postMessage(this.samples.buffer, [this.samples.buffer]);
        this.samples = new Int16Array(this.frameSize); this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("darius-voice-capture", VoiceCapture);
