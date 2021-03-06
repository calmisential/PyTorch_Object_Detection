from pathlib import Path

import torch


from register import YOLOxSCFG

from load_yaml import load_yamls
from utils.video import Video


VIDEO_DIR = ""
SAVE_VIDEO = True   # True: 先一帧一帧地检测，然后将结果保存为一个视频序列；False: 实时显示检测结果，但不保存
VIDEO_SAVE_DIR = ""
MODEL_FILE_NAME = ""
model = YOLOxSCFG

if __name__ == '__main__':
    model_full_path = Path("./saved_model").joinpath(MODEL_FILE_NAME)

    model_name = model.name
    config = model.cfg_file
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print("PyTorch version: {}, Device: {}".format(torch.__version__, device))
    cfg = load_yamls(model_yaml=config, device=device, model_name=model_name)

    model_trainer = model.get_trainer(cfg)

    model_trainer.load(weights_path=model_full_path)

    v = Video(cfg, model_trainer.model, device, VIDEO_DIR, VIDEO_SAVE_DIR,
              pipeline_func=model_trainer.forward_pipeline)
    if SAVE_VIDEO:
        v.write()
    else:
        v.show()
