"""Sequence ordering, split isolation and reproducible state expectations."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from app.sequences import sequence_request, validate_sequences, validate_frame_order, outage_modalities
from app.sequence_job import run_sequence_job

ROOT=Path(__file__).resolve().parents[2]


def sequence():
    base=json.loads((ROOT/'contracts/fixtures/CaptureRequest.json').read_text())
    base['world']['instances']=json.loads((ROOT/'contracts/fixtures/WorldSpec.json').read_text())['instances']
    base['temporal']={'schema_version':'lab.v1','kind':'TemporalCapture','profile':'rig-motion-drift.v1',
        'reference_time_s':0,'velocity_world_m_per_s':[2,0,0],'yaw_rate_rad_per_s':.1,'sensor_drift':[],
        'object_motion':[{'instance_id':'aircraft-1','velocity_world_m_per_s':[0,0,-3],'yaw_rate_rad_per_s':.2}]}
    return {'schema_version':'lab.v1','kind':'SequenceSpec','profile':'temporal-sequence.v1',
        'sequence_id':'seq-a','family_id':'family-a','variant_id':'clean','group_id':'layout-a',
        'split':'train','frame_count':32,'frame_interval_s':.2,'start_time_s':0,'base_capture':base,
        'outages':[{'start_frame':8,'stop_frame':16,'modalities':['rgb','ir','lidar']}],
        'operating_events':[{'frame_index':1,'instance_id':'aircraft-1','operating_state':'running'}]}


def test_materialized_frames_restore_nominal_platform_and_thermal_link_without_mutating_source():
    spec=sequence(); before=copy.deepcopy(spec)
    prior={'id':'thermal_state_json','sha256':'a'*64,'byte_length':10,'media_type':'application/json'}
    request=sequence_request(spec,10,prior)
    assert request['plan']['simulation_time_s']==2
    assert request['rig']['T_world_from_rig'][3]==4
    a=.2
    np.testing.assert_allclose(np.array(request['rig']['T_world_from_rig']).reshape(4,4)[:3,:3],
        [[np.cos(a),0,np.sin(a)],[0,1,0],[-np.sin(a),0,np.cos(a)]])
    assert request['environment']['thermal_history']=='continued'
    assert request['environment']['thermal_state']==prior
    assert request['world']['instances'][0]['operating_state']=='running'
    # Reference world is unchanged by object motion; the worker evaluates sample times.
    assert request['world']['instances'][0]['T_world_from_asset']==spec['base_capture']['world']['instances'][0]['T_world_from_asset']
    assert spec==before
    assert sequence_request(spec,0,None)['environment']['thermal_history']=='equilibrated'
    with pytest.raises(ValueError): sequence_request(spec,1,None)


def test_splits_reject_sequence_family_group_and_scene_leakage():
    first=sequence(); other=copy.deepcopy(first)
    other.update(sequence_id='seq-b',variant_id='fog')
    validate_sequences([first,other])
    for change in ({'split':'test'},{'family_id':'other','split':'test'},
                   {'family_id':'other','group_id':'other','split':'test'}):
        bad=copy.deepcopy(other); bad.update(change)
        with pytest.raises(ValueError): validate_sequences([first,bad])
    with pytest.raises(ValueError): validate_sequences([first,first])
    bad=copy.deepcopy(other); bad['base_capture']['world']['seed']+=1
    with pytest.raises(ValueError): validate_sequences([first,bad])


def test_gaps_duplicates_disorder_and_time_drift_are_explicit_errors():
    spec=sequence()
    frames=[{'frame_index':i,'capture_time_s':i*.2} for i in range(5)]
    validate_frame_order(spec,frames,complete=False)
    for bad in (frames[1:],frames[:2]+frames[3:],frames[::-1],frames+[frames[-1]]):
        with pytest.raises(ValueError): validate_frame_order(spec,bad,complete=False)
    bad=copy.deepcopy(frames); bad[2]['capture_time_s']+=.01
    with pytest.raises(ValueError): validate_frame_order(spec,bad,complete=False)
    with pytest.raises(ValueError): validate_frame_order(spec,frames,complete=True)


def test_outages_have_exact_boundaries_and_recovery():
    spec=sequence()
    assert outage_modalities(spec,7)==set()
    assert outage_modalities(spec,8)=={'rgb','ir','lidar'}
    assert outage_modalities(spec,15)=={'rgb','ir','lidar'}
    assert outage_modalities(spec,16)==set()
    bad=copy.deepcopy(spec); bad['outages'][0]['stop_frame']=33
    with pytest.raises(ValueError): validate_sequences([bad])
    bad=copy.deepcopy(spec); bad['frame_interval_s']=.001
    bad['base_capture']['rig']['sensors'][2]['scan_duration_s']=.1
    with pytest.raises(ValueError): validate_sequences([bad])


def test_published_gap_is_rejected_before_capture_or_state_rewrite(tmp_path):
    spec=sequence()
    (tmp_path/'dataset'/'seq-a-000001').mkdir(parents=True)
    with pytest.raises(ValueError,match='frame gap'):
        run_sequence_job([spec],tmp_path)
    assert not (tmp_path/'dataset'/'seq-a-000000').exists()


def test_os_managed_writer_lock_prevents_second_coordinator(tmp_path):
    import sqlite3
    owner=sqlite3.connect(tmp_path/'sequence-lock.sqlite3')
    owner.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(ValueError,match='another writer'):
            run_sequence_job([sequence()],tmp_path)
    finally:
        owner.rollback(); owner.close()


def test_resume_rejects_changed_configuration_without_overwriting_its_identity(tmp_path):
    from app.sequences import canonical_hash
    spec=sequence()
    state={'version':'temporal-sequence-job.v1','state':'cancelled','request_sha256':canonical_hash([spec]),'completed':{},'error':None}
    path=tmp_path/'sequence-job.json'; path.write_text(json.dumps(state))
    changed=copy.deepcopy(spec); changed['frame_count']+=1
    with pytest.raises(ValueError,match='specification changed'):
        run_sequence_job([changed],tmp_path,resume=True)
    assert json.loads(path.read_text())==state
