from darius_api.worker import source_revision


def test_worker_revision_detects_schema_updates_and_ignores_runtime_logs(tmp_path):
    schema=tmp_path/'canvas_h3.py';schema.write_text('old schema')
    old=source_revision(tmp_path)
    (tmp_path/'worker.log').write_text('job output')
    assert source_revision(tmp_path)==old
    schema.write_text('new body swap schema')
    assert source_revision(tmp_path)!=old
    old=source_revision(tmp_path)
    (tmp_path/'new_adapter.py').write_text('new recipe')
    assert source_revision(tmp_path)!=old
