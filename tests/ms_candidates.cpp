#include <windows.h>
#include <msctf.h>
#include <iostream>
#include <string>
struct CandidateString: IUnknown { virtual HRESULT STDMETHODCALLTYPE GetString(BSTR*)=0; virtual HRESULT STDMETHODCALLTYPE GetIndex(ULONG*)=0; };
struct CandidateList: IUnknown { virtual HRESULT STDMETHODCALLTYPE EnumCandidates(IUnknown**)=0; virtual HRESULT STDMETHODCALLTYPE GetCandidate(ULONG,CandidateString**)=0; virtual HRESULT STDMETHODCALLTYPE GetCandidateNum(ULONG*)=0; };
struct Search: IUnknown {virtual HRESULT STDMETHODCALLTYPE GetDisplayName(BSTR*)=0;virtual HRESULT STDMETHODCALLTYPE GetSearchCandidates(BSTR,BSTR,CandidateList**)=0;};
int main(){
    CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED);SetConsoleOutputCP(65001);
    GUID cls,search;CLSIDFromString(L"{81D4E9C9-1D3B-41BC-9E6C-4B40BF79E35E}",&cls);
    CLSIDFromString(L"{87a2ad8f-f27b-4920-8501-67602280175d}",&search);
    ITfThreadMgr* mgr=nullptr;HRESULT h=CoCreateInstance(CLSID_TF_ThreadMgr,nullptr,CLSCTX_ALL,IID_ITfThreadMgr,(void**)&mgr);
    TfClientId tid;if(SUCCEEDED(h))h=mgr->Activate(&tid);ITfFunctionProvider* provider=nullptr;
    ITfInputProcessorProfileMgr* profiles=nullptr;GUID profile;CLSIDFromString(L"{FA550B04-5AD7-411F-A5AC-CA038EC515D7}",&profile);
    if(SUCCEEDED(h)&&SUCCEEDED(CoCreateInstance(CLSID_TF_InputProcessorProfiles,nullptr,CLSCTX_ALL,IID_ITfInputProcessorProfileMgr,(void**)&profiles))){
        HRESULT activated=profiles->ActivateProfile(TF_PROFILETYPE_INPUTPROCESSOR,0x0804,cls,profile,nullptr,0);
        std::cout<<"thread activation "<<std::hex<<activated<<"\n";profiles->Release();}
    if(SUCCEEDED(h))h=mgr->GetFunctionProvider(cls,&provider);
    if(FAILED(h))h=CoCreateInstance(cls,nullptr,CLSCTX_ALL,IID_ITfFunctionProvider,(void**)&provider);
    Search*s=nullptr;if(SUCCEEDED(h))h=provider->GetFunction(GUID_NULL,search,(IUnknown**)&s);
    if(FAILED(h)){std::cout<<"provider HRESULT "<<std::hex<<h<<"\n";return 1;}
    for(auto raw:{L"quan",L"xian",L"qy",L"quany",L"qyi",L"xa",L"xi'an",L"zgr",L"zgyd"}){
        BSTR q=SysAllocString(raw),app=SysAllocString(L"ReformPinyin.Evaluation");CandidateList* list=nullptr;
        h=s->GetSearchCandidates(q,app,&list);SysFreeString(q);SysFreeString(app);std::wcout<<raw<<L"\t";
        if(FAILED(h)||!list){std::wcout<<L"HRESULT "<<std::hex<<h<<L"\n";continue;}
        ULONG count=0;list->GetCandidateNum(&count);for(ULONG i=0;i<count&&i<30;i++){CandidateString* cand=nullptr;
        if(SUCCEEDED(list->GetCandidate(i,&cand))){BSTR str=nullptr;if(SUCCEEDED(cand->GetString(&str))){char out[1024]={};
        WideCharToMultiByte(CP_UTF8,0,str,-1,out,1024,nullptr,nullptr);std::cout<<out<<"\t";SysFreeString(str);}cand->Release();}}
        std::cout<<"\n";list->Release();
    }
    s->Release();provider->Release();mgr->Deactivate();mgr->Release();CoUninitialize();return 0;
}
