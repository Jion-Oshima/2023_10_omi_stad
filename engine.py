# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
"""
Train and eval functions used in main.py
"""
from comet_ml import Experiment
import math
import os
import sys
from typing import Iterable
from tqdm import tqdm

import torch

import util.misc as utils
from util.plot_utils import plot_frame_boxes, plot_clip_boxes
from datasets.coco_eval import CocoEvaluator
from datasets.panoptic_eval import PanopticEvaluator
from models.person_encoder import make_same_person_list


def train_one_epoch(model: torch.nn.Module, criterion: torch.nn.Module,
                    data_loader: Iterable, optimizer: torch.optim.Optimizer,
                    device: torch.device, epoch: int,
                    psn_encoder: torch.nn.Module, psn_criterion: torch.nn.Module,
                    log: dict, ex: Experiment):
    # model.train()
    # criterion.train()
    psn_encoder.train()
    psn_criterion.train()

    step = len(data_loader) * (epoch - 1)

    pbar_batch = tqdm(enumerate(data_loader), total=len(data_loader), leave=False)
    for i, (samples, targets) in pbar_batch:
        samples = samples.to(device)
        # targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
        targets = [[{k: v.to(device) for k, v in t.items()} for t in vtgt] for vtgt in targets]
        targets = [t for vtgt in targets for t in vtgt]
        b, c, t, h, w = samples.size()
        samples = samples.permute(0, 2, 1, 3, 4)
        samples = samples.reshape(b * t, c, h, w)

        outputs = model(samples)
        _, indices_ex = criterion(outputs, targets)
        p_queries = [outputs["queries"][0, t][idx[0]] for t, idx in enumerate(indices_ex)]  # if idx[0] == None: 空のテンソルが格納
        n_gt_bbox_list = [idx[0].size(0) for idx in indices_ex]  # [frame_id] = n gt bbox
        p_queries = torch.cat(p_queries, 0)
        p_feature_queries = psn_encoder(p_queries)
        p_loss, same_person_label = psn_criterion(p_feature_queries, indices_ex, b, t)
        matching_scores = make_same_person_list(p_feature_queries.detach(), same_person_label, n_gt_bbox_list, b, t)

        optimizer.zero_grad()
        p_loss.backward()
        optimizer.step()

        log["psn_loss"].update(p_loss.item(), b)
        log["diff_psn_score"].update(matching_scores["diff_psn_score"], b)
        log["same_psn_score"].update(matching_scores["same_psn_score"], b)
        log["total_psn_score"].update(matching_scores["total_psn_score"], b)

        pbar_batch.set_postfix_str(f'loss={log["psn_loss"].val}')
        pbar_batch.set_postfix_str(f'match score={log["total_psn_score"].val}')

        ex.log_metric("batch_psn_loss", log["psn_loss"].val, step=step + i)
        ex.log_metric("batch_diff_psn_score", log["diff_psn_score"].val, step=step + i)
        ex.log_metric("batch_same_psn_score", log["same_psn_score"].val, step=step + i)
        ex.log_metric("batch_total_psn_score", log["total_psn_score"].val, step=step + i)


@torch.no_grad()
def evaluate(model, criterion, postprocessors, data_loader, device, output_dir, psn_encoder, psn_criterion, log, ex):
    psn_encoder.eval()
    psn_criterion.eval()

    pbar_batch = tqdm(data_loader, total=len(data_loader), leave=False)
    for samples, targets in pbar_batch:
        samples = samples.to(device)
        targets = [[{k: v.to(device) for k, v in t.items()} for t in vtgt] for vtgt in targets]
        targets = [t for vtgt in targets for t in vtgt]
        b, c, t, h, w = samples.size()
        samples = samples.permute(0, 2, 1, 3, 4)
        samples = samples.reshape(b * t, c, h, w)

        outputs = model(samples)
        loss_dict, indices_ex = criterion(outputs, targets)
        p_queries = [outputs["queries"][0, t][idx[0]] for t, idx in enumerate(indices_ex)]  # if idx[0] == None: 空のテンソルが格納
        n_gt_bbox_list = [idx[0].size(0) for idx in indices_ex]
        p_queries = torch.cat(p_queries, 0)
        p_feature_queries = psn_encoder(p_queries)
        p_loss, same_person_label = psn_criterion(p_feature_queries, indices_ex, b, t)
        matching_scores = make_same_person_list(p_feature_queries.detach(), same_person_label, n_gt_bbox_list, b, t)

        log["psn_loss"].update(p_loss.item(), b)
        log["diff_psn_score"].update(matching_scores["diff_psn_score"], b)
        log["same_psn_score"].update(matching_scores["same_psn_score"], b)
        log["total_psn_score"].update(matching_scores["total_psn_score"], b)

        pbar_batch.set_postfix_str(f'loss={log["psn_loss"].val}')
        pbar_batch.set_postfix_str(f'match score={log["total_psn_score"].val}')

        continue
        orig_target_sizes = torch.stack([t["size"] for t in targets], dim=0)
        # orig_target_sizes = torch.stack([t["orig_size"] for t in targets], dim=0)
        results = postprocessors['bbox'](outputs, orig_target_sizes)
        if 'segm' in postprocessors.keys():
            target_sizes = torch.stack([t["size"] for t in targets], dim=0)
            results = postprocessors['segm'](results, outputs, orig_target_sizes, target_sizes)
        # res = {target['image_id'].item(): output for target, output in zip(targets, results)}
        # if coco_evaluator is not None:
        #     coco_evaluator.update(res)

        # plot
        # plot_frame_boxes(samples[0], results[0])
        plot_clip_boxes(samples[0:t], results[0:t])
        # plot_frame_boxes(samples.tensors[0], results[0])
        continue
