"""
XTTS-v2 Fine-tuning Script
Runs GPT training for voice adaptation

Usage:
    python train_xtts.py --train_csv /path/to/train.csv --eval_csv /path/to/eval.csv \
        --output_path /path/to/output --num_epochs 10 --batch_size 2 --language en
"""

import os
import gc
import sys
import argparse
from datetime import datetime

# Ensure TTS module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def train_xtts(
    train_csv: str,
    eval_csv: str,
    output_path: str,
    num_epochs: int = 10,
    batch_size: int = 2,
    grad_accum: int = 1,
    language: str = "en",
    max_audio_length: int = 255995  # ~11.6 seconds at 22050 Hz
):
    """
    Fine-tune XTTS-v2 on custom dataset.
    
    Returns:
        Tuple of (config_path, checkpoint_path, vocab_path, trainer_output_path, speaker_ref)
    """
    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.layers.xtts.trainer.gpt_trainer import GPTArgs, GPTTrainer, GPTTrainerConfig, XttsAudioConfig
    from TTS.utils.manage import ModelManager

    print(f"[{datetime.now().isoformat()}] Starting XTTS-v2 fine-tuning...")
    print(f"  Train CSV: {train_csv}")
    print(f"  Eval CSV: {eval_csv}")
    print(f"  Output: {output_path}")
    print(f"  Epochs: {num_epochs}")
    print(f"  Batch size: {batch_size}")
    print(f"  Language: {language}")
    
    # Training configuration
    RUN_NAME = "XTTS_FT"
    PROJECT_NAME = "Honora_Voice_Training"
    DASHBOARD_LOGGER = "tensorboard"
    
    OUT_PATH = os.path.join(output_path, "run", "training")
    os.makedirs(OUT_PATH, exist_ok=True)
    
    # Dataset configuration
    config_dataset = BaseDatasetConfig(
        formatter="coqui",
        dataset_name="custom_voice",
        path=os.path.dirname(train_csv),
        meta_file_train=train_csv,
        meta_file_val=eval_csv,
        language=language,
    )
    
    # Download XTTS v2.0 base model files
    CHECKPOINTS_OUT_PATH = os.path.join(OUT_PATH, "XTTS_v2.0_original_model_files/")
    os.makedirs(CHECKPOINTS_OUT_PATH, exist_ok=True)
    
    # Model file URLs
    DVAE_CHECKPOINT_LINK = "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/dvae.pth"
    MEL_NORM_LINK = "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/mel_stats.pth"
    TOKENIZER_FILE_LINK = "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/vocab.json"
    XTTS_CHECKPOINT_LINK = "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/model.pth"
    XTTS_CONFIG_LINK = "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/config.json"
    
    # Local paths
    DVAE_CHECKPOINT = os.path.join(CHECKPOINTS_OUT_PATH, "dvae.pth")
    MEL_NORM_FILE = os.path.join(CHECKPOINTS_OUT_PATH, "mel_stats.pth")
    TOKENIZER_FILE = os.path.join(CHECKPOINTS_OUT_PATH, "vocab.json")
    XTTS_CHECKPOINT = os.path.join(CHECKPOINTS_OUT_PATH, "model.pth")
    XTTS_CONFIG_FILE = os.path.join(CHECKPOINTS_OUT_PATH, "config.json")
    
    # Download DVAE files if needed
    if not os.path.isfile(DVAE_CHECKPOINT) or not os.path.isfile(MEL_NORM_FILE):
        print(" > Downloading DVAE files...")
        ModelManager._download_model_files([MEL_NORM_LINK, DVAE_CHECKPOINT_LINK], CHECKPOINTS_OUT_PATH, progress_bar=True)
    
    # Download XTTS v2.0 files if needed
    if not os.path.isfile(TOKENIZER_FILE) or not os.path.isfile(XTTS_CHECKPOINT):
        print(" > Downloading XTTS v2.0 base model files...")
        ModelManager._download_model_files(
            [TOKENIZER_FILE_LINK, XTTS_CHECKPOINT_LINK, XTTS_CONFIG_LINK],
            CHECKPOINTS_OUT_PATH,
            progress_bar=True
        )
    
    print(f"[{datetime.now().isoformat()}] Model files ready. Configuring training...")
    
    # Model arguments
    model_args = GPTArgs(
        max_conditioning_length=132300,  # 6 secs
        min_conditioning_length=66150,   # 3 secs
        debug_loading_failures=False,
        max_wav_length=max_audio_length,
        max_text_length=200,
        mel_norm_file=MEL_NORM_FILE,
        dvae_checkpoint=DVAE_CHECKPOINT,
        xtts_checkpoint=XTTS_CHECKPOINT,
        tokenizer_file=TOKENIZER_FILE,
        gpt_num_audio_tokens=1026,
        gpt_start_audio_token=1024,
        gpt_stop_audio_token=1025,
        gpt_use_masking_gt_prompt_approach=True,
        gpt_use_perceiver_resampler=True,
    )
    
    # Audio configuration
    audio_config = XttsAudioConfig(
        sample_rate=22050,
        dvae_sample_rate=22050,
        output_sample_rate=24000
    )
    
    # Training configuration
    config = GPTTrainerConfig(
        epochs=num_epochs,
        output_path=OUT_PATH,
        model_args=model_args,
        run_name=RUN_NAME,
        project_name=PROJECT_NAME,
        run_description="XTTS fine-tuning for Honora",
        dashboard_logger=DASHBOARD_LOGGER,
        audio=audio_config,
        batch_size=batch_size,
        batch_group_size=48,
        eval_batch_size=batch_size,
        num_loader_workers=2,  # Reduced for CPU/Mac
        eval_split_max_size=256,
        print_step=10,  # More frequent progress output
        plot_step=100,
        log_model_step=100,
        save_step=500,
        save_n_checkpoints=1,
        save_checkpoints=True,
        print_eval=False,
        optimizer="AdamW",
        optimizer_wd_only_on_weights=True,
        optimizer_params={"betas": [0.9, 0.96], "eps": 1e-8, "weight_decay": 1e-2},
        lr=5e-06,
        lr_scheduler="MultiStepLR",
        lr_scheduler_params={"milestones": [50000 * 18, 150000 * 18, 300000 * 18], "gamma": 0.5, "last_epoch": -1},
        test_sentences=[],
    )
    
    print(f"[{datetime.now().isoformat()}] Initializing model...")
    
    # Initialize model
    model = GPTTrainer.init_from_config(config)
    
    # Load training samples
    print(f"[{datetime.now().isoformat()}] Loading dataset samples...")
    train_samples, eval_samples = load_tts_samples(
        [config_dataset],
        eval_split=True,
        eval_split_max_size=config.eval_split_max_size,
        eval_split_size=config.eval_split_size,
    )
    
    print(f"  Train samples: {len(train_samples)}")
    print(f"  Eval samples: {len(eval_samples)}")
    
    # Initialize trainer
    trainer = Trainer(
        TrainerArgs(
            restore_path=None,
            skip_train_epoch=False,
            start_with_eval=False,
            grad_accum_steps=grad_accum,
        ),
        config,
        output_path=OUT_PATH,
        model=model,
        train_samples=train_samples,
        eval_samples=eval_samples,
    )
    
    print(f"[{datetime.now().isoformat()}] Starting training loop...")
    
    # Train!
    trainer.fit()
    
    print(f"[{datetime.now().isoformat()}] Training complete!")
    
    # Get speaker reference (longest audio file)
    samples_len = [len(item["text"].split(" ")) for item in train_samples]
    longest_text_idx = samples_len.index(max(samples_len))
    speaker_ref = train_samples[longest_text_idx]["audio_file"]
    
    trainer_out_path = trainer.output_path
    
    # Cleanup
    del model, trainer, train_samples, eval_samples
    gc.collect()
    
    print(f"[{datetime.now().isoformat()}] Fine-tuning complete!")
    print(f"  Output path: {trainer_out_path}")
    print(f"  Speaker reference: {speaker_ref}")
    
    return XTTS_CONFIG_FILE, XTTS_CHECKPOINT, TOKENIZER_FILE, trainer_out_path, speaker_ref


def main():
    parser = argparse.ArgumentParser(description="XTTS-v2 Fine-tuning Script")
    parser.add_argument("--train_csv", required=True, help="Path to training CSV")
    parser.add_argument("--eval_csv", required=True, help="Path to evaluation CSV")
    parser.add_argument("--output_path", required=True, help="Output directory")
    parser.add_argument("--num_epochs", type=int, default=10, help="Number of epochs")
    parser.add_argument("--batch_size", type=int, default=2, help="Batch size")
    parser.add_argument("--grad_accum", type=int, default=1, help="Gradient accumulation steps")
    parser.add_argument("--language", default="en", help="Language code")
    parser.add_argument("--max_audio_length", type=int, default=255995, help="Max audio length in samples")
    
    args = parser.parse_args()
    
    config_path, checkpoint_path, vocab_path, trainer_output, speaker_ref = train_xtts(
        train_csv=args.train_csv,
        eval_csv=args.eval_csv,
        output_path=args.output_path,
        num_epochs=args.num_epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        language=args.language,
        max_audio_length=args.max_audio_length,
    )
    
    print(f"\n=== Training Complete ===")
    print(f"Config: {config_path}")
    print(f"Checkpoint: {checkpoint_path}")
    print(f"Vocab: {vocab_path}")
    print(f"Trainer output: {trainer_output}")
    print(f"Speaker reference: {speaker_ref}")


if __name__ == "__main__":
    main()
