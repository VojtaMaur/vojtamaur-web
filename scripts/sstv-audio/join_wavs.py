import re
import wave
from pathlib import Path

# --- Nastaveni ---
GAP_SECONDS = 1
MAX_WAV_DATA_BYTES = 3_900_000_000  # bezpecne pod ~4 GiB limitem klasickeho RIFF/WAV

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input_wav"
OUTPUT_DIR = BASE_DIR / "output_wav"


def natural_key(path: Path):
    """Radi 2.wav pred 10.wav; funguje samozrejme i pro 000001.wav atd."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", path.name)]


def get_format(path: Path):
    with wave.open(str(path), "rb") as w:
        return {
            "nchannels": w.getnchannels(),
            "sampwidth": w.getsampwidth(),
            "framerate": w.getframerate(),
            "comptype": w.getcomptype(),
            "compname": w.getcompname(),
            "nframes": w.getnframes(),
        }


def compatible(fmt, reference):
    return (
        fmt["nchannels"] == reference["nchannels"]
        and fmt["sampwidth"] == reference["sampwidth"]
        and fmt["framerate"] == reference["framerate"]
        and fmt["comptype"] == reference["comptype"]
    )


def output_name(index: int, split: bool) -> Path:
    if split:
        return OUTPUT_DIR / f"combined-with-gaps_{index:03d}.wav"
    return OUTPUT_DIR / "combined-with-gaps.wav"


def main():
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    files = sorted(INPUT_DIR.glob("*.wav"), key=natural_key)
    if not files:
        raise SystemExit(
            f"Ve slozce {INPUT_DIR} nejsou zadne .wav soubory.\n"
            "Vloz je do slozky 'input' vedle tohoto skriptu a spust skript znovu."
        )

    reference = get_format(files[0])
    if reference["comptype"] != "NONE":
        raise ValueError("Skript ocekava nekomprimovane PCM WAV soubory.")

    bytes_per_frame = reference["nchannels"] * reference["sampwidth"]
    gap_frames = round(reference["framerate"] * GAP_SECONDS)
    gap_bytes = gap_frames * bytes_per_frame
    silence = b"\x00" * gap_bytes

    infos = []
    total_data_bytes = 0

    for path in files:
        fmt = get_format(path)
        if not compatible(fmt, reference):
            raise ValueError(f"Nekompatibilni WAV: {path.name}")

        data_bytes = fmt["nframes"] * bytes_per_frame
        infos.append((path, fmt["nframes"], data_bytes))
        total_data_bytes += data_bytes

    if len(files) > 1:
        total_data_bytes += gap_bytes * (len(files) - 1)

    split = total_data_bytes > MAX_WAV_DATA_BYTES

    print(f"Nalezeno WAV souboru: {len(files)}")
    print(f"Vstup:  {INPUT_DIR}")
    print(f"Vystup: {OUTPUT_DIR}")
    print(f"Mezera mezi obrazky: {GAP_SECONDS} s")
    print(f"Format: {reference['framerate']} Hz, {reference['sampwidth'] * 8}-bit, "
          f"{reference['nchannels']} kanal(y)")

    if split:
        print("Archiv je vetsi nez bezpecny limit klasickeho WAV -> automaticky se rozdeli do volume souboru.")
    else:
        print("Archiv se vejde do jednoho klasickeho WAV.")

    volume_index = 1
    current_path = output_name(volume_index, split)
    out = wave.open(str(current_path), "wb")
    out.setnchannels(reference["nchannels"])
    out.setsampwidth(reference["sampwidth"])
    out.setframerate(reference["framerate"])
    out.setcomptype(reference["comptype"], reference["compname"])

    current_data_bytes = 0
    files_in_volume = 0
    written_files = 0

    def close_volume(writer, path, count):
        writer.close()
        print(f"HOTOVO: {path.name} ({count} obrazku)")

    try:
        for file_index, (path, nframes, data_bytes) in enumerate(infos):
            # Mezera patri mezi dva SSTV prenosy.
            needs_gap = written_files > 0
            required = data_bytes + (gap_bytes if needs_gap else 0)

            # Pokud by dalsi obrazek pretekl pres bezpecny RIFF/WAV limit,
            # uzavreme volume a zalozime dalsi.
            if split and files_in_volume > 0 and current_data_bytes + required > MAX_WAV_DATA_BYTES:
                close_volume(out, current_path, files_in_volume)

                volume_index += 1
                current_path = output_name(volume_index, split)
                out = wave.open(str(current_path), "wb")
                out.setnchannels(reference["nchannels"])
                out.setsampwidth(reference["sampwidth"])
                out.setframerate(reference["framerate"])
                out.setcomptype(reference["comptype"], reference["compname"])
                current_data_bytes = 0
                files_in_volume = 0

                # Zachovame 1 s mezeru i na hranici volume.
                if needs_gap:
                    out.writeframes(silence)
                    current_data_bytes += gap_bytes

            elif needs_gap:
                out.writeframes(silence)
                current_data_bytes += gap_bytes

            with wave.open(str(path), "rb") as w:
                out.writeframes(w.readframes(nframes))

            current_data_bytes += data_bytes
            files_in_volume += 1
            written_files += 1
            print(f"[{written_files}/{len(files)}] {path.name}")

        close_volume(out, current_path, files_in_volume)
        out = None

    finally:
        if out is not None:
            out.close()

    print()
    print(f"CELKEM: {written_files} obrazku")
    if split:
        print(f"Vytvoreno volume souboru: {volume_index}")
    print("Vse je ve slozce 'output'.")


if __name__ == "__main__":
    main()
