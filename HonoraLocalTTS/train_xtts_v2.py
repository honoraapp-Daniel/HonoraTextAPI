"""
XTTS v2 fine-tuning entrypoint for RunPod training.

Usage:
  python -u HonoraLocalTTS/train_xtts_v2.py \
    --dataset_dir train_dataset \
    --output_dir train_output/<run_name> \
    --run_name <run_name> \
    --epochs 10 \
    --batch_size 2 \
    --grad_accum 1 \
    --lr 5e-6 \
    --mixed_precision fp16 \
    --gpu 0
"""

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime
from typing import List, Tuple


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "|", "\t"])
        return dialect.delimiter
    except csv.Error:
        return ";"


def _parse_metadata(metadata_path: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    with open(metadata_path, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = _detect_delimiter(sample)
        reader = csv.reader(handle, delimiter=delimiter)
        rows = [row for row in reader if row]

    if not rows:
        raise ValueError("metadata.csv is empty")

    header = [cell.strip().lower() for cell in rows[0]]
    has_header = any(
        name in header
        for name in ("filename", "file", "path", "text", "normalized_text")
    )

    if has_header:
        filename_idx = None
        text_idx = None
        normalized_idx = None
        for idx, name in enumerate(header):
            if name in ("filename", "file", "path"):
                filename_idx = idx
            if name == "text":
                text_idx = idx
            if name == "normalized_text":
                normalized_idx = idx
        if filename_idx is None:
            raise ValueError("metadata.csv header missing filename column")
        if normalized_idx is not None:
            text_idx = normalized_idx
        if text_idx is None:
            raise ValueError("metadata.csv header missing text column")
        data_rows = rows[1:]
    else:
        filename_idx = 0
        text_idx = 1 if len(rows[0]) > 1 else None
        if text_idx is None:
            raise ValueError("metadata.csv missing text column")
        data_rows = rows

    items: List[Tuple[str, str]] = []
    for row in data_rows:
        if len(row) <= max(filename_idx, text_idx):
            continue
        filename = row[filename_idx].strip().strip("\"")
        text = row[text_idx].strip().strip("\"")
        if not filename or not text:
            continue
        items.append((filename, text))

    if not items:
        raise ValueError("metadata.csv has no valid rows")

    return items, header


def _resolve_wav_path(dataset_dir: str, filename: str) -> Tuple[str, str]:
    if os.path.isabs(filename):
        abs_path = filename
        rel_path = os.path.relpath(abs_path, dataset_dir)
        return abs_path, rel_path

    if filename.startswith("wavs/") or filename.startswith("wavs\\"):
        abs_path = os.path.join(dataset_dir, filename)
        return abs_path, filename.replace("\\", "/")

    abs_path = os.path.join(dataset_dir, "wavs", filename)
    rel_path = os.path.join("wavs", filename).replace("\\", "/")
    return abs_path, rel_path


def _build_splits(
    dataset_dir: str,
    metadata_path: str,
    output_dir: str,
    val_split: float,
    seed: int,
) -> Tuple[str, str, int, int]:
    items, header = _parse_metadata(metadata_path)

    resolved: List[Tuple[str, str]] = []
    missing: List[str] = []
    for filename, text in items:
        abs_path, rel_path = _resolve_wav_path(dataset_dir, filename)
        if not os.path.exists(abs_path):
            missing.append(filename)
            continue
        resolved.append((rel_path, text))

    if not resolved:
        raise ValueError("No audio files found for metadata rows")

    rng = random.Random(seed)
    rng.shuffle(resolved)

    val_count = int(len(resolved) * val_split)
    if len(resolved) > 1:
        val_count = max(1, val_count)
    else:
        val_count = 0

    eval_items = resolved[:val_count]
    train_items = resolved[val_count:]

    train_csv = os.path.join(output_dir, "train.csv")
    eval_csv = os.path.join(output_dir, "eval.csv")

    os.makedirs(output_dir, exist_ok=True)

    with open(train_csv, "w", encoding="utf-8", newline="") as handle:
        for rel_path, text in train_items:
            handle.write(f"{rel_path}|{text}\n")

    with open(eval_csv, "w", encoding="utf-8", newline="") as handle:
        for rel_path, text in eval_items:
            handle.write(f"{rel_path}|{text}\n")

    if missing:
        warn_path = os.path.join(output_dir, "missing_audio.json")
        with open(warn_path, "w", encoding="utf-8") as handle:
            json.dump({"missing": missing}, handle, indent=2)

    return train_csv, eval_csv, len(train_items), len(eval_items)


def _train_xtts(
    train_csv: str,
    eval_csv: str,
    output_dir: str,
    run_name: str,
    epochs: int,
    batch_size: int,
    grad_accum: int,
    lr: float,
    mixed_precision: str,
    max_steps: int,
    num_workers: int,
):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.layers.xtts.trainer.gpt_trainer import (
        GPTArgs,
        GPTTrainer,
        GPTTrainerConfig,
        XttsAudioConfig,
    )
    from TTS.utils.manage import ModelManager

    print(f"[{_now_iso()}] Starting XTTS v2 fine-tune")
    print(f"  Train CSV: {train_csv}")
    print(f"  Eval CSV: {eval_csv}")
    print(f"  Output dir: {output_dir}")
    print(f"  Run name: {run_name}")

    dataset_config = BaseDatasetConfig(
        formatter="coqui",
        dataset_name="honora_custom_voice",
        path=os.path.dirname(train_csv),
        meta_file_train=train_csv,
        meta_file_val=eval_csv,
        language="en",
    )

    checkpoints_dir = os.path.join(output_dir, "xtts_base")
    os.makedirs(checkpoints_dir, exist_ok=True)

    dvae_ckpt = os.path.join(checkpoints_dir, "dvae.pth")
    mel_stats = os.path.join(checkpoints_dir, "mel_stats.pth")
    tokenizer_file = os.path.join(checkpoints_dir, "vocab.json")
    xtts_ckpt = os.path.join(checkpoints_dir, "model.pth")
    xtts_config = os.path.join(checkpoints_dir, "config.json")

    if not os.path.isfile(dvae_ckpt) or not os.path.isfile(mel_stats):
        print(" > Downloading DVAE files...")
        ModelManager._download_model_files(
            [
                "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/mel_stats.pth",
                "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/dvae.pth",
            ],
            checkpoints_dir,
            progress_bar=True,
        )

    if not os.path.isfile(tokenizer_file) or not os.path.isfile(xtts_ckpt):
        print(" > Downloading XTTS v2 base model files...")
        ModelManager._download_model_files(
            [
                "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/vocab.json",
                "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/model.pth",
                "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/config.json",
            ],
            checkpoints_dir,
            progress_bar=True,
        )

    model_args = GPTArgs(
        max_conditioning_length=132300,
        min_conditioning_length=66150,
        debug_loading_failures=False,
        max_wav_length=255995,
        max_text_length=200,
        mel_norm_file=mel_stats,
        dvae_checkpoint=dvae_ckpt,
        xtts_checkpoint=xtts_ckpt,
        tokenizer_file=tokenizer_file,
        gpt_num_audio_tokens=1026,
        gpt_start_audio_token=1024,
        gpt_stop_audio_token=1025,
        gpt_use_masking_gt_prompt_approach=True,
        gpt_use_perceiver_resampler=True,
    )

    audio_config = XttsAudioConfig(
        sample_rate=22050,
        dvae_sample_rate=22050,
        output_sample_rate=24000,
    )

    config = GPTTrainerConfig(
        epochs=epochs,
        output_path=output_dir,
        model_args=model_args,
        run_name=run_name,
        project_name="Honora_XTTS_Training",
        run_description="XTTS v2 fine-tuning",
        dashboard_logger="tensorboard",
        audio=audio_config,
        batch_size=batch_size,
        batch_group_size=48,
        eval_batch_size=batch_size,
        num_loader_workers=num_workers,
        eval_split_max_size=256,
        print_step=10,
        plot_step=100,
        log_model_step=100,
        save_step=500,
        save_n_checkpoints=1,
        save_checkpoints=True,
        print_eval=False,
        optimizer="AdamW",
        optimizer_wd_only_on_weights=True,
        optimizer_params={"betas": [0.9, 0.96], "eps": 1e-8, "weight_decay": 1e-2},
        lr=lr,
        lr_scheduler="MultiStepLR",
        lr_scheduler_params={
            "milestones": [50000 * 18, 150000 * 18, 300000 * 18],
            "gamma": 0.5,
            "last_epoch": -1,
        },
        test_sentences=[],
    )

    if max_steps > 0 and hasattr(config, "max_steps"):
        setattr(config, "max_steps", max_steps)

    model = GPTTrainer.init_from_config(config)

    print(f"[{_now_iso()}] Loading dataset samples...")
    train_samples, eval_samples = load_tts_samples(
        [dataset_config],
        eval_split=True,
        eval_split_max_size=config.eval_split_max_size,
        eval_split_size=config.eval_split_size,
    )

    print(f"  Train samples: {len(train_samples)}")
    print(f"  Eval samples: {len(eval_samples)}")

    trainer_args = TrainerArgs(
        restore_path=None,
        skip_train_epoch=False,
        start_with_eval=False,
        grad_accum_steps=grad_accum,
    )
    if hasattr(trainer_args, "mixed_precision"):
        trainer_args.mixed_precision = mixed_precision
    elif hasattr(trainer_args, "precision"):
        trainer_args.precision = mixed_precision

    trainer = Trainer(
        trainer_args,
        config,
        output_path=output_dir,
        model=model,
        train_samples=train_samples,
        eval_samples=eval_samples,
    )

    print(f"[{_now_iso()}] Starting training loop...")
    trainer.fit()
    print(f"[{_now_iso()}] Training complete.")


def main():
    parser = argparse.ArgumentParser(description="XTTS v2 fine-tuning runner")
    parser.add_argument("--dataset_dir", required=True, help="Dataset root containing wavs/ and metadata.csv")
    parser.add_argument("--output_dir", required=True, help="Directory to write checkpoints/logs")
    parser.add_argument("--run_name", required=True, help="Run name for this training session")
    parser.add_argument("--epochs", type=int, default=10, help="Number of epochs")
    parser.add_argument("--max_steps", type=int, default=0, help="Optional max steps override")
    parser.add_argument("--batch_size", type=int, default=2, help="Batch size")
    parser.add_argument("--grad_accum", type=int, default=1, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=5e-6, help="Learning rate")
    parser.add_argument("--mixed_precision", default="fp16", help="Mixed precision mode")
    parser.add_argument("--gpu", type=int, default=0, help="GPU index")
    parser.add_argument("--val_split", type=float, default=0.1, help="Validation split fraction")
    parser.add_argument("--num_workers", type=int, default=2, help="Data loader workers")

    args = parser.parse_args()

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(args.gpu))

    dataset_dir = os.path.abspath(args.dataset_dir)
    output_dir = os.path.abspath(args.output_dir)

    wavs_dir = os.path.join(dataset_dir, "wavs")
    metadata_path = os.path.join(dataset_dir, "metadata.csv")
    if not os.path.isdir(wavs_dir) or not os.path.isfile(metadata_path):
        raise SystemExit("Dataset directory must contain wavs/ and metadata.csv")

    os.makedirs(output_dir, exist_ok=True)

    train_csv, eval_csv, train_count, eval_count = _build_splits(
        dataset_dir,
        metadata_path,
        output_dir,
        val_split=args.val_split,
        seed=42,
    )

    print(f"[{_now_iso()}] Dataset prepared. Train={train_count}, Eval={eval_count}")

    _train_xtts(
        train_csv=train_csv,
        eval_csv=eval_csv,
        output_dir=output_dir,
        run_name=args.run_name,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        lr=args.lr,
        mixed_precision=args.mixed_precision,
        max_steps=args.max_steps,
        num_workers=args.num_workers,
    )


if __name__ == "__main__":
    main()
