import torch
import torch.nn.functional as F
from torchvision.ops import batched_nms

from core.SSD.anchor import DefaultBoxes
from utils.tools import reverse_letter_box


class Decode:
    def __init__(self, cfg, original_image_size, input_image_size):
        """

        Args:
            cfg: 配置文件
            original_image_size: [h, w], 原始图片大小
            input_image_size: int, 输入SSD的图片的固定大小
        """
        self.device = cfg["device"]
        self.priors_xywh = DefaultBoxes(cfg).__call__(xyxy=False).to(self.device)
        self.priors_xywh = torch.unsqueeze(self.priors_xywh, dim=0)
        self.top_k = cfg["Decode"]["max_num_output_boxes"]
        self.num_classes = cfg["Model"]["num_classes"] + 1

        self.variance = cfg["Loss"]["variance"]
        self.scale_xy = self.variance[0]
        self.scale_wh = self.variance[1]

        self.conf_thresh = cfg["Decode"]["confidence_threshold"]
        self.nms_thresh = cfg["Decode"]["nms_threshold"]

        self.original_image_size = original_image_size
        self.input_image_size = input_image_size

    def _decode(self, bboxes_in, scores_in):
        """

        Args:
            bboxes_in: torch.Tensor, shape: (batch_size, num_priors, 4)
            scores_in: torch.Tensor, shape: (batch_size, num_priors, self.num_classes)

        Returns:

        """
        bboxes_in[:, :, :2] = self.scale_xy * bboxes_in[:, :, :2]
        bboxes_in[:, :, 2:] = self.scale_wh * bboxes_in[:, :, 2:]
        bboxes_in[:, :, :2] = bboxes_in[:, :, :2] * self.priors_xywh[:, :, 2:] + self.priors_xywh[:, :, :2]
        bboxes_in[:, :, 2:] = torch.exp(bboxes_in[:, :, 2:]) * self.priors_xywh[:, :, 2:]

        xmin = bboxes_in[:, :, 0] - 0.5 * bboxes_in[:, :, 2]
        xmax = bboxes_in[:, :, 0] + 0.5 * bboxes_in[:, :, 2]
        ymin = bboxes_in[:, :, 1] - 0.5 * bboxes_in[:, :, 3]
        ymax = bboxes_in[:, :, 1] + 0.5 * bboxes_in[:, :, 3]
        bboxes_in[:, :, 0] = xmin
        bboxes_in[:, :, 1] = ymin
        bboxes_in[:, :, 2] = xmax
        bboxes_in[:, :, 3] = ymax
        return bboxes_in, F.softmax(scores_in, dim=-1)

    def __call__(self, outputs):
        loc_data, conf_data = outputs

        bboxes, probs = self._decode(loc_data, conf_data)

        batch_size = bboxes.size(0)
        assert batch_size == 1, "仅支持单张图片作为预测输入。"
        bbox = torch.squeeze(bboxes, dim=0)  # (num_priors, 4)
        prob = torch.squeeze(probs, dim=0)  # (num_priors, self.num_classes)
        num_priors = self.priors_xywh.size(0)

        # 限制在[0, 1]范围内
        decoded_boxes = torch.clamp(bbox, min=0, max=1)
        # (num_priors, 4) - > (num_priors, 21, 4)
        decoded_boxes = decoded_boxes.repeat(1, self.num_classes).reshape(prob.size()[0], -1, 4)

        # 为每一个类别创建标签信息(0~20)
        labels = torch.arange(self.num_classes, dtype=torch.int32, device=self.device)
        labels = labels.view(1, -1).expand_as(prob)  # shape: (num_priors, num_classes)

        # 移除背景类别的信息
        boxes = decoded_boxes[:, 1:, :]  # (num_priors, 20, 4)
        scores = prob[:, 1:]  # (num_priors, 20)
        labels = labels[:, 1:]   # (num_priors, 20)

        # 对于每一个box，它都有可能属于这(num_classes-1)个类别之一
        boxes_all = boxes.reshape(-1, 4)   # (num_priors*20, 4)
        scores_all = scores.reshape(-1)  # (num_priors*20)
        labels_all = labels.reshape(-1)   # (num_priors*20)

        # 移除低概率目标
        inds = torch.nonzero(scores_all > self.conf_thresh).squeeze(1)
        boxes_all, scores_all, labels_all = boxes_all[inds, :], scores_all[inds], labels_all[inds]

        # 移除面积很小的边界框
        w, h = boxes_all[:, 2] - boxes_all[:, 0], boxes_all[:, 3] - boxes_all[:, 1]
        keep = (w >= 1 / 300) & (h >= 1 / 300)
        keep = keep.nonzero().squeeze(1)
        boxes_all, scores_all, labels_all = boxes_all[keep], scores_all[keep], labels_all[keep]

        boxes_all, scores_all, labels_all = boxes_all.to(torch.float32), scores_all.to(
            torch.float32), labels_all.to(torch.int32)

        # nms
        keep = batched_nms(boxes_all, scores_all, labels_all, iou_threshold=self.nms_thresh)
        keep = keep[:self.top_k]
        boxes_out = boxes_all[keep]
        scores_out = scores_all[keep]
        labels_out = labels_all[keep]

        # 将boxes坐标变换到原始图片上
        boxes = reverse_letter_box(h=self.original_image_size[0], w=self.original_image_size[1],
                                   input_size=self.input_image_size, boxes=boxes_out, xywh=False)

        return boxes, scores_out, labels_out - 1
