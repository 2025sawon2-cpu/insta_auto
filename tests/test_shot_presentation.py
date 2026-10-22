from hotpost.shot_presentation import interval_receipt, supports_product


def test_file_core_cannot_override_interval_identity(tmp_path):
    f=tmp_path/'frame.jpg';f.write_bytes(b'pixels')
    shot=dict(start=0,end=1,sha256='source',source_role='core',frames=[f])
    value=dict(product_visible=False,product_role='preparation',visible_information=[],
               frame_product_visibility=[False],
               visual_cluster='room',composition=.7,clarity=.8,product_coverage=0,
               mask_product_overlap=0,uncertainty='Only supplied frames')
    receipt=interval_receipt(shot,value)
    assert receipt['source_window']==[0,1] and not supports_product(receipt)
    value.update(product_visible=True,product_role='general_context')
    assert not supports_product(interval_receipt(shot,value))
    value.update(product_role='related_product',visible_information=['front fit'])
    value['frame_product_visibility']=[True]
    assert supports_product(interval_receipt(shot,value))


def test_mixed_preparation_does_not_inherit_core_even_when_model_claims_visible(tmp_path):
    f=tmp_path/'frame.jpg';f.write_bytes(b'pixels')
    shot=dict(start=0,end=4,sha256='42ac',source_role='core',frames=[f,f,f])
    value=dict(product_visible=True,product_role='promoted_product',visible_information=['fit'],
               frame_product_visibility=[False,True,True],visual_cluster='outfit',composition=.7,
               clarity=.8,product_coverage=.4,mask_product_overlap=0,uncertainty='Preparation then outfit')
    assert not supports_product(interval_receipt(shot,value))


def test_context_restriction_does_not_hide_actual_featured_subject_from_observer(tmp_path):
    from hotpost.scene_analysis import _observe
    f=tmp_path/'frame.jpg';f.write_bytes(b'actual-frame')
    shot=dict(id='soup',start=0,end=1,sha256='source',frames=[f],source_role='context_only',
        featured_subject='미역국',product_source_kind='core_product',
        context_usage_limits=['Cannot demonstrate an unseen soaking additive.'])
    def generate(settings,instruction,payload,media):
        row=payload['shots'][0]
        assert row['featured_subject']=='미역국' and row['product_source_kind']=='core_product'
        assert row['source_role']=='context_only' and row['context_usage_limits']==shot['context_usage_limits']
        return {'shots':[{'id':'soup','observation':'Visible soup; no soaking additive shown.',
            'tags':['soup'],'visual_type':'product','presentation':dict(product_visible=True,
                product_role='promoted_product',frame_product_visibility=[True],visible_information=['soup'],
                visual_cluster='soup',composition=.7,clarity=.8,product_coverage=.5,mask_product_overlap=0,
                uncertainty='No additive demonstration')} ]}
    result=_observe(None,[shot],generate)['soup']
    assert supports_product(result['shot_presentation'])
    assert shot['source_role']=='context_only' and 'unseen' in shot['context_usage_limits'][0]
