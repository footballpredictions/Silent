"""Permission probes must not leave unpublished calls in the agent account."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.vk_agent_auth import test_calls_permission

CALL_ID='11111111-2222-3333-4444-555555555555'
LINK='https://vk.com/call/join/test-unpublished-room'


class PermissionCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_permission_probe_finishes_only_its_own_new_call(self):
        rpc=AsyncMock(side_effect=[{'response':{'call_id':CALL_ID,'join_link':LINK}},{'response':1}])
        with patch('app.services.vk_agent_auth.vk_api_call',rpc):
            result=await test_calls_permission('test-token-not-a-real-credential')
        self.assertEqual(result,(True,'OK'))
        self.assertEqual(rpc.await_count,2)
        self.assertEqual(rpc.await_args_list[1].args,('calls.forceFinish','test-token-not-a-real-credential',{'call_id':CALL_ID}))

    async def test_invalid_join_link_still_cleans_the_created_test_call(self):
        rpc=AsyncMock(side_effect=[{'response':{'call_id':CALL_ID}},{'response':1}])
        with patch('app.services.vk_agent_auth.vk_api_call',rpc):
            ok,_=await test_calls_permission('test-token')
        self.assertFalse(ok)
        self.assertEqual(rpc.await_count,2)

    async def test_cleanup_failure_is_not_reported_as_success(self):
        rpc=AsyncMock(side_effect=[{'response':{'call_id':CALL_ID,'join_link':LINK}},
                                  {'error':{'error_code':10,'error_msg':'Internal server error'}}])
        with patch('app.services.vk_agent_auth.vk_api_call',rpc):
            ok,_=await test_calls_permission('test-token')
        self.assertFalse(ok)

    async def test_start_failure_does_not_finish_any_existing_call(self):
        rpc=AsyncMock(return_value={'error':{'error_code':9,'error_msg':'Flood control'}})
        with patch('app.services.vk_agent_auth.vk_api_call',rpc):
            ok,_=await test_calls_permission('test-token')
        self.assertFalse(ok)
        self.assertEqual(rpc.await_count,1)

    async def test_missing_call_id_cannot_claim_cleanup_succeeded(self):
        rpc=AsyncMock(return_value={'response':{'join_link':LINK}})
        with patch('app.services.vk_agent_auth.vk_api_call',rpc):
            ok,_=await test_calls_permission('test-token')
        self.assertFalse(ok)
        self.assertEqual(rpc.await_count,1)


if __name__=='__main__':unittest.main()
