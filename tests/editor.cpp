// Exercise the installed input profile with a real RichEdit control in this process.
#define UNICODE
#include <windows.h>
#include <msctf.h>
#include <richedit.h>
#include <iostream>
#include <string>
static ITfKeystrokeMgr* keys;
static void pump(int ms){
    auto until=GetTickCount64()+ms;
    do {MSG m;while(PeekMessageW(&m,0,0,0,PM_REMOVE)){
        BOOL eat=FALSE;
        if(m.message==WM_KEYDOWN&&keys&&SUCCEEDED(keys->TestKeyDown(m.wParam,m.lParam,&eat))&&eat){
            keys->KeyDown(m.wParam,m.lParam,&eat);if(eat)continue;}
        TranslateMessage(&m);DispatchMessageW(&m);}
        Sleep(3);
    }while(GetTickCount64()<until);
}
static void key(HWND edit,WPARAM k){
    PostMessageW(edit,WM_KEYDOWN,k,1|(MapVirtualKeyW(k,0)<<16));pump(100);
    PostMessageW(edit,WM_KEYUP,k,0xc0000001|(MapVirtualKeyW(k,0)<<16));pump(100);
}
int main(int argc,char**argv){
    OleInitialize(nullptr);LoadLibraryW(L"Msftedit.dll");
    ITfThreadMgr* tm=nullptr;TfClientId tid=0;
    CoCreateInstance(CLSID_TF_ThreadMgr,nullptr,CLSCTX_ALL,IID_ITfThreadMgr,(void**)&tm);
    if(!tm||FAILED(tm->Activate(&tid)))return 1;
    tm->QueryInterface(IID_ITfKeystrokeMgr,(void**)&keys);
    HWND top=CreateWindowExW(0,L"STATIC",L"改革拼音独立试打",WS_OVERLAPPEDWINDOW,60,60,500,160,0,0,0,0);
    HWND box=CreateWindowExW(0,MSFTEDIT_CLASS,L"",WS_CHILD|WS_VISIBLE|ES_MULTILINE,0,0,460,100,top,0,0,0);
    ShowWindow(top,SW_SHOWNORMAL);SetForegroundWindow(top);SetFocus(box);
    ITfInputProcessorProfileMgr* profiles=nullptr;
    CoCreateInstance(CLSID_TF_InputProcessorProfiles,nullptr,CLSCTX_ALL,IID_ITfInputProcessorProfileMgr,(void**)&profiles);
    GUID cls,profile;CLSIDFromString(L"{A62A60A8-421D-4A86-91D7-767E708A2221}",&cls);
    CLSIDFromString(L"{55498CE1-7AE7-456A-A3A6-6334F8759916}",&profile);
    if(!profiles||FAILED(profiles->ActivateProfile(1,0x804,cls,profile,0,0)))return 2;
    pump(500);
    for(int i=0;i<3;i++){
        SetWindowTextW(box,L"");pump(120);key(box,'Q');key(box,'Y');
        HWND popup=FindWindowExW(nullptr,nullptr,L"ReformPinyin.Candidates",nullptr);
        bool shown=popup&&IsWindowVisible(popup);std::cout<<"popup="<<shown<<" ";
        if(i==2&&shown)SendMessageW(popup,WM_LBUTTONUP,0,MAKELPARAM(20,28*3+4));
        else key(box,i==0?VK_SPACE:'2');
        pump(250);wchar_t output[256]={};GetWindowTextW(box,output,256);
        char utf[512]={};WideCharToMultiByte(CP_UTF8,0,output,-1,utf,512,nullptr,nullptr);
        std::cout<<"committed="<<utf<<std::endl;
        if(!shown||wcslen(output)!=2||output[0]<128)return 3;
    }
    DestroyWindow(top);tm->Deactivate();OleUninitialize();return 0;
}
