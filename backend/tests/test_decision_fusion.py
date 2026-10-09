import numpy as np
import pytest
from learning.decision_fusion import fuse, fuse_snapshots


def prediction(yaw=0, cls=0, x=0):
    return {"boxes":np.array([[x,0,0,4,2,2,yaw]],dtype=np.float32),"classes":np.array([cls]),"scores":np.array([.9])}


def test_consensus_merges_same_class_and_preserves_pi_periodic_yaw():
    out=fuse([prediction(),prediction(np.pi),prediction(x=20)],[True,True,False])
    assert len(out["boxes"]) == 1
    assert abs(out["boxes"][0,-1]) < 1e-6
    assert out["scores"][0] == pytest.approx(.9)
    assert fuse([prediction(),prediction(cls=1),prediction()],[True,True,False])["classes"].tolist() == [0,1]


def test_all_missing_is_empty_and_unavailable_values_are_not_read():
    poison={"boxes":None,"classes":None,"scores":None}
    out=fuse([poison]*3,[False]*3)
    assert out["boxes"].shape == (0,7)
    assert fuse([prediction(),poison,poison],[True,False,False])["scores"][0] == pytest.approx(.9)


def test_empty_available_sensor_reduces_consensus_score_without_creating_boxes():
    empty={"boxes":np.empty((0,7)),"classes":np.empty(0,dtype=int),"scores":np.empty(0)}
    out=fuse([prediction(),empty,empty],[True,True,True])
    assert len(out["boxes"]) == 1
    assert out["scores"][0] == pytest.approx(.3)


def test_snapshot_consensus_respects_sensor_availability_and_does_not_double_count():
    out=fuse_snapshots([[prediction(),prediction()]]*3,[True,True,True])
    assert len(out["boxes"]) == 1 and out["scores"][0] == pytest.approx(.9)
    poison={"boxes":None,"classes":None,"scores":None}
    assert len(fuse_snapshots([[poison,poison]]*3,[False]*3)["boxes"]) == 0
