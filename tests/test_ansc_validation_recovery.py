from pathlib import Path
import importlib.util
s=importlib.util.spec_from_file_location('recovery',Path(__file__).with_name('51_ansc_validation_recovery.py'))
if not s.origin or not Path(s.origin).exists():
 s=importlib.util.spec_from_file_location('recovery',Path(__file__).resolve().parents[1]/'scripts/51_ansc_validation_recovery.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
HEAD='AGENȚIA NAȚIONALĂ PENTRU SOLUȚIONAREA CONTESTAȚIILOR\nD E C I Z I E\nNr. 03D-123-22 Data: 20.09.2022\n'
def test_rejected_on_merits_with_intervening_phrase():
 x=m.parse([HEAD,'d e c i d e:\nSe respinge ca neîntemeiată contestația nr. 02/19/22.'])
 assert x['proposed_outcome']=='rejected' and x['complaints']==[('02/19/22','rejected')]
def test_partial_is_not_full_admission():
 x=m.parse([HEAD,'decide:\nSe admite parțial contestația nr. 02/20/22.'])
 assert x['proposed_outcome']=='partially_admitted'
def test_contracting_authority_is_not_ansc():
 x=m.parse([HEAD.replace('AGENȚIA NAȚIONALĂ PENTRU SOLUȚIONAREA CONTESTAȚIILOR','AGENȚIA SERVICII PUBLICE'),'decide: Se admite contestația nr. 02/20/22.'])
 assert x['reason']=='no_own_dated_ANSC_merits_header'
def test_interim_order_not_final_decision():
 assert m.parse([HEAD.replace('03D-','03DS-'),'dispune: Se suspendă procedura.'])['reason']=='no_own_dated_ANSC_merits_header'
def test_no_anchor_is_unresolved():
 assert m.parse([HEAD,'Contestatorul solicită admiterea contestației nr.02/20/22'])['reason']=='no_resolutory_anchor'
def test_inadmissibility_never_becomes_negative():
 assert m.parse([HEAD,'decide: Se respinge contestația nr.02/20/22 ca inadmisibilă.'])['reason']=='non_merits_or_ambiguous_operative_item'
def test_two_complaints_keep_mixed_outcomes():
 x=m.parse([HEAD,'decide:\n1. Se admite contestația nr.02/20/22.\n2. Se respinge contestația nr.02/21/22.'])
 assert x['proposed_outcome']=='mixed' and len(x['complaints'])==2

def test_ansc_cover_letter_without_decision_heading_is_not_own_decision():
 assert m.parse([HEAD.replace('D E C I Z I E','Scrisoare'), 'decide: Se admite contestația nr.02/20/22.'])['reason']=='no_own_dated_ANSC_merits_header'
