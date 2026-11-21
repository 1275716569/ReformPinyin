#define UNICODE
#define _UNICODE
#include <windows.h>
#include <msctf.h>
#include <initguid.h>
#include <inputscope.h>
#include <string>
#include <vector>
#include <algorithm>
#include <functional>
#include <memory>

static const GUID tipId={0xa62a60a8,0x421d,0x4a86,{0x91,0xd7,0x76,0x7e,0x70,0x8a,0x22,0x21}};
static const GUID profileId={0x55498ce1,0x7ae7,0x456a,{0xa3,0xa6,0x63,0x34,0xf8,0x75,0x99,0x16}};
static HMODULE module;
static LONG objects;
using std::wstring;
template<class T> void drop(T*& p){if(p){p->Release();p=nullptr;}}
static wstring dllPath(){wchar_t p[32768];DWORD n=GetModuleFileNameW(module,p,32768);return wstring(p,n);}
static wstring call(const wstring& client,const wstring& op,const wstring& arg=L""){
    DWORD session=0; ProcessIdToSessionId(GetCurrentProcessId(),&session);
    wstring pipe=L"\\\\.\\pipe\\ReformPinyin.v1."+std::to_wstring(session);
    wstring req=client+L"\t"+op+L"\t"+arg;
    wchar_t result[32768]={}; DWORD received=0;
    if(!CallNamedPipeW(pipe.c_str(),req.data(),DWORD(req.size()*2),result,sizeof(result)-2,&received,100))return L"";
    return wstring(result);
}
class Edit : public ITfEditSession {
    LONG refs=1;
    std::function<HRESULT(TfEditCookie)> task;
public:
    Edit(std::function<HRESULT(TfEditCookie)> f):task(f){}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID i,void**p) override{
        if(i!=IID_IUnknown&&i!=IID_ITfEditSession){*p=nullptr;return E_NOINTERFACE;} *p=this;AddRef();return S_OK;}
    ULONG STDMETHODCALLTYPE AddRef() override{return ++refs;}
    ULONG STDMETHODCALLTYPE Release() override{auto n=--refs;if(!n)delete this;return n;}
    HRESULT STDMETHODCALLTYPE DoEditSession(TfEditCookie e) override{return task(e);}
};
class Tip : public ITfTextInputProcessor,public ITfKeyEventSink,public ITfThreadMgrEventSink,public ITfTextEditSink {
    LONG refs=1;
    ITfThreadMgr* mgr=nullptr;ITfContext* ctx=nullptr;
    DWORD focusCookie=TF_INVALID_COOKIE,editCookie=TF_INVALID_COOKIE;
    TfClientId id=0;
    wstring client,raw;
    std::vector<wstring> words;
    int page=0;HWND popup=nullptr;RECT caret{};bool ownEditPending=false,english=false;
    bool hint=false, shiftArmed=false;
    bool singleQuoteOpen=false,doubleQuoteOpen=false;
    int hover=-1, dpi=96;
    unsigned long generation=0;
    bool pending=false;

    int px(int value) const { return MulDiv(value,dpi,96); }
    int itemAt(POINT pt) const {
        RECT area{};
        if(hint||!GetClientRect(popup,&area)||pt.x<px(4)||pt.x>=area.right-px(4)||pt.y<px(36))return -1;
        int index=(pt.y-px(36))/px(32);
        return index<(int)words.size()?index:-1;
    }
    void paint(HWND h){
        PAINTSTRUCT ps;HDC dc=BeginPaint(h,&ps);RECT rc;GetClientRect(h,&rc);
        FillRect(dc,&rc,(HBRUSH)GetStockObject(WHITE_BRUSH));SetBkMode(dc,TRANSPARENT);
        auto font=CreateFontW(-px(17),0,0,0,FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Microsoft YaHei UI");
        auto old=SelectObject(dc,font);
        auto label=[&](const wstring& text,RECT box,COLORREF color,UINT align){
            SetTextColor(dc,color);
            DrawTextW(dc,text.data(),(int)text.size(),&box,align|DT_VCENTER|DT_SINGLELINE|DT_END_ELLIPSIS|DT_NOPREFIX);
        };
        if(hint){
            label(english?L"英":L"中",rc,RGB(0,95,169),DT_CENTER);
        }else{
            label(raw,{px(14),0,rc.right-px(54),px(34)},RGB(49,53,58),DT_LEFT);
            label(std::to_wstring(page+1),{rc.right-px(48),0,rc.right-px(14),px(34)},RGB(101,105,110),DT_RIGHT);
            HBRUSH line=CreateSolidBrush(RGB(227,230,234));
            RECT divider{px(8),px(34),rc.right-px(8),px(35)};FillRect(dc,&divider,line);DeleteObject(line);
            for(int i=0;i<(int)words.size();++i){
                int top=px(36)+i*px(32);
                RECT item{px(4),top,rc.right-px(4),top+px(32)};
                if(i==0||i==hover){
                    HBRUSH fill=CreateSolidBrush(i==0?RGB(232,242,251):RGB(244,245,247));
                    FillRect(dc,&item,fill);DeleteObject(fill);
                    if(i==0){
                        RECT bar{item.left,top+px(6),item.left+px(3),item.bottom-px(6)};
                        HBRUSH accent=CreateSolidBrush(RGB(0,99,177));FillRect(dc,&bar,accent);DeleteObject(accent);
                    }
                }
                label(std::to_wstring(i+1),{px(14),top,px(38),item.bottom},RGB(96,101,108),DT_LEFT);
                label(words[i],{px(44),top,item.right-px(8),item.bottom},RGB(30,32,35),DT_LEFT);
            }
        }
        SelectObject(dc,old);DeleteObject(font);EndPaint(h,&ps);
    }
    static LRESULT CALLBACK popupProc(HWND h,UINT m,WPARAM w,LPARAM l){
        Tip* self=reinterpret_cast<Tip*>(GetWindowLongPtrW(h,GWLP_USERDATA));
        if(m==WM_NCCREATE){self=(Tip*)((CREATESTRUCTW*)l)->lpCreateParams;SetWindowLongPtrW(h,GWLP_USERDATA,(LONG_PTR)self);}
        if(!self)return DefWindowProcW(h,m,w,l);
        POINT pt{(short)LOWORD(l),(short)HIWORD(l)};
        switch(m){
        case WM_MOUSEACTIVATE:return MA_NOACTIVATE;
        case WM_LBUTTONUP:self->choose(self->itemAt(pt));return 0;
        case WM_MOUSEMOVE:{
            int i=self->itemAt(pt);
            if(i!=self->hover){
                self->hover=i;InvalidateRect(h,nullptr,FALSE);
                TRACKMOUSEEVENT track{sizeof(track),TME_LEAVE,h,0};TrackMouseEvent(&track);
            }
            return 0;
        }
        case WM_MOUSELEAVE:self->hover=-1;InvalidateRect(h,nullptr,FALSE);return 0;
        case WM_MOUSEWHEEL:if(!self->hint)self->turn((short)HIWORD(w)<0?1:-1);return 0;
        case WM_TIMER:if(w==1&&self->hint){KillTimer(h,1);ShowWindow(h,SW_HIDE);self->hint=false;}return 0;
        case WM_PAINT:self->paint(h);return 0;
        }
        return DefWindowProcW(h,m,w,l);
    }
    void clear(bool reset){
        ++generation;pending=false;raw.clear();words.clear();page=0;hint=false;
        if(popup){KillTimer(popup,1);ShowWindow(popup,SW_HIDE);}
        if(reset)call(client,L"reset");
    }
    void bind(ITfContext* c){
        if(ctx==c)return;
        shiftArmed=false;
        unadvise(ctx,editCookie);
        drop(ctx);ctx=c;if(ctx)ctx->AddRef();
        advise(ctx,IID_ITfTextEditSink,(ITfTextEditSink*)this,editCookie);clear(true);
    }
    static void advise(IUnknown* obj,REFIID iid,IUnknown* sink,DWORD& cookie){
        ITfSource* src=nullptr;if(obj&&SUCCEEDED(obj->QueryInterface(IID_ITfSource,(void**)&src))){src->AdviseSink(iid,sink,&cookie);src->Release();}}
    static void unadvise(IUnknown* obj,DWORD& cookie){
        ITfSource* src=nullptr;if(obj&&cookie!=TF_INVALID_COOKIE&&SUCCEEDED(obj->QueryInterface(IID_ITfSource,(void**)&src))){src->UnadviseSink(cookie);src->Release();}cookie=TF_INVALID_COOKIE;}
    HRESULT edit(DWORD flags,std::function<HRESULT(TfEditCookie)> f){
        if(!ctx)return E_FAIL;auto e=new Edit(f);HRESULT result=E_FAIL;
        HRESULT hr=ctx->RequestEditSession(id,e,TF_ES_SYNC|flags,&result);e->Release();return FAILED(hr)?hr:result;
    }
    bool allowed(){
        HWND h=GetFocus();
        if(h){wchar_t cls[64]={};GetClassNameW(h,cls,64);
            if((!_wcsicmp(cls,L"Edit")||!_wcsnicmp(cls,L"RichEdit",8))&&(GetWindowLongPtrW(h,GWL_STYLE)&ES_PASSWORD))return false;}
        TF_STATUS status{};if(!ctx||FAILED(ctx->GetStatus(&status))||(status.dwDynamicFlags&TF_SD_READONLY))return false;
        return edit(TF_ES_READ,[&](TfEditCookie ec){
            TF_SELECTION s{};ULONG n=0;if(FAILED(ctx->GetSelection(ec,TF_DEFAULT_SELECTION,1,&s,&n))||!n)return E_FAIL;
            bool safe=true;ITfReadOnlyProperty* prop=nullptr;
            if(SUCCEEDED(ctx->GetAppProperty(GUID_PROP_INPUTSCOPE,&prop))){
                VARIANT v;VariantInit(&v);
                if(SUCCEEDED(prop->GetValue(ec,s.range,&v))&&v.vt==VT_UNKNOWN&&v.punkVal){
                    ITfInputScope* scope=nullptr;if(SUCCEEDED(v.punkVal->QueryInterface(IID_ITfInputScope,(void**)&scope))){
                        InputScope* types=nullptr;UINT count=0;if(SUCCEEDED(scope->GetInputScopes(&types,&count))){
                            for(UINT i=0;i<count;i++)if(types[i]==IS_PASSWORD||types[i]==IS_NUMERIC_PASSWORD||types[i]==IS_NUMERIC_PIN||types[i]==IS_PRIVATE)safe=false;
                            CoTaskMemFree(types);}scope->Release();}}
                VariantClear(&v);prop->Release();}
            ITfContextView* view=nullptr;if(SUCCEEDED(ctx->GetActiveView(&view))){BOOL clip;RECT r{};
                if(SUCCEEDED(view->GetTextExt(ec,s.range,&r,&clip)))caret=r;view->Release();}
            s.range->Release();return safe?S_OK:E_ACCESSDENIED;})==S_OK;
    }
    void display(bool mode){
        if(!popup){
            WNDCLASSW wc{};wc.hInstance=module;wc.lpfnWndProc=popupProc;
            wc.lpszClassName=L"ReformPinyin.Candidates";wc.hCursor=LoadCursor(nullptr,IDC_ARROW);
            RegisterClassW(&wc);
            popup=CreateWindowExW(WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE|WS_EX_TOPMOST,wc.lpszClassName,
                L"改革拼音候选",WS_POPUP|WS_BORDER,0,0,0,0,nullptr,nullptr,module,this);
        }
        if(!popup)return;
        KillTimer(popup,1);hint=mode;hover=-1;
        dpi=GetDpiForWindow(GetFocus());if(!dpi)dpi=96;
        int width=px(mode?48:264);
        int height=mode?px(36):px(40)+(int)words.size()*px(32);
        MONITORINFO mi{sizeof(mi)};GetMonitorInfoW(MonitorFromRect(&caret,MONITOR_DEFAULTTONEAREST),&mi);
        int x=std::clamp<int>(caret.left,mi.rcWork.left,std::max<LONG>(mi.rcWork.left,mi.rcWork.right-width));
        int y=caret.bottom+height>mi.rcWork.bottom?std::max<int>(mi.rcWork.top,caret.top-height):caret.bottom;
        SetWindowPos(popup,HWND_TOPMOST,x,y,width,height,SWP_NOACTIVATE|SWP_SHOWWINDOW);
        InvalidateRect(popup,nullptr,FALSE);
        if(mode)SetTimer(popup,1,800,nullptr);
    }
    void show(const wstring& reply){
        words.clear();size_t i=0;
        while(i<reply.size()){size_t j=reply.find(L'\t',i);words.push_back(reply.substr(i,j-i));if(j==wstring::npos)break;i=j+1;}
        display(false);
    }
    void insert(wstring text,int index,bool switchAfter=false,const wstring& historySuffix=L""){
        if(!ctx||text.empty()||pending)return;
        ctx->AddRef();
        auto target=std::shared_ptr<ITfContext>(ctx,[](ITfContext*c){c->Release();});
        AddRef();
        auto self=std::shared_ptr<Tip>(this,[](Tip*t){t->Release();});
        auto ticket=generation;
        pending=true;
        auto session=new Edit([self,target,ticket,text,index,switchAfter,historySuffix](TfEditCookie ec)->HRESULT{
            if(self->generation!=ticket||self->ctx!=target.get()){
                self->ownEditPending=false;
                return S_FALSE;
            }
            TF_SELECTION selection{};ULONG fetched=0;
            HRESULT hr=target->GetSelection(ec,TF_DEFAULT_SELECTION,1,&selection,&fetched);
            if(SUCCEEDED(hr)&&fetched==1&&selection.range){
                hr=selection.range->SetText(ec,0,text.data(),static_cast<LONG>(text.size()));
                if(SUCCEEDED(hr)){
                    selection.range->Collapse(ec,TF_ANCHOR_END);
                    selection.style={TF_AE_NONE,FALSE};
                    target->SetSelection(ec,1,&selection);
                }
                selection.range->Release();
            }else if(SUCCEEDED(hr))hr=E_FAIL;
            self->pending=false;
            if(SUCCEEDED(hr)){
                if(index>=0)call(self->client,L"choose",std::to_wstring(index));
                self->clear(index==-1);
                if(!historySuffix.empty())call(self->client,L"append",historySuffix);
                if(switchAfter){self->english=true;self->display(true);}
            }
            if(FAILED(hr))self->ownEditPending=false;
            return hr;
        });
        HRESULT result=E_FAIL;
        ownEditPending=true;
        HRESULT request=ctx->RequestEditSession(id,session,TF_ES_READWRITE|TF_ES_ASYNCDONTCARE,&result);
        session->Release();
        if(FAILED(request)||FAILED(result)){pending=false;ownEditPending=false;}
    }
    void punctuate(const wstring& punctuation){
        if(punctuation.empty()||pending)return;
        if(!raw.empty()&&!words.empty()){
            insert(words[0]+punctuation,page*5,false,punctuation);
            return;
        }
        if(!raw.empty()){
            insert(raw+punctuation,-1);
            return;
        }
        insert(punctuation,-2,false,punctuation);
    }
    void choose(int offset){
        if(offset<0||offset>=(int)words.size()||pending)return;
        insert(words[offset],page*5+offset);
    }
    void turn(int d){int next=std::max(0,page+d);auto s=call(client,L"page",std::to_wstring(next));if(!s.empty()){page=next;show(s);}}
    wstring punctuationFor(WPARAM k,bool shifted){
        switch(k){
        case VK_OEM_COMMA:return shifted?L"《":L"，";
        case VK_OEM_PERIOD:return shifted?L"》":L"。";
        case VK_OEM_2:return shifted?L"？":L"/";
        case VK_OEM_1:return shifted?L"：":L"；";
        case VK_OEM_7:
            if(shifted)return doubleQuoteOpen?L"”":L"“";
            return singleQuoteOpen?L"’":L"‘";
        case VK_OEM_5:return shifted?L"|":L"、";
        case VK_OEM_3:return shifted?L"~":L"·";
        case VK_OEM_4:return shifted?L"「":L"【";
        case VK_OEM_6:return shifted?L"」":L"】";
        case VK_OEM_MINUS:return shifted?L"——":L"-";
        case VK_OEM_PLUS:return shifted?L"+":L"=";
        default:break;
        }
        if(shifted&&k>='0'&&k<='9'){
            static const wchar_t* symbols[]={L"）",L"！",L"@",L"#",L"¥",L"%",L"……",L"&",L"*",L"（"};
            return symbols[k-'0'];
        }
        return L"";
    }
    bool wants(WPARAM k){
        if(GetKeyState(VK_CONTROL)<0||GetKeyState(VK_MENU)<0||GetKeyState(VK_LWIN)<0||GetKeyState(VK_RWIN)<0)return false;
        if(english)return false;
        bool shifted=GetKeyState(VK_SHIFT)<0;
        if(k>='A'&&k<='Z')return !shifted&&!(GetKeyState(VK_CAPITAL)&1);
        if(k==VK_OEM_7&&!shifted&&!raw.empty())return true;
        if(!punctuationFor(k,shifted).empty())return true;
        return !raw.empty()&&(k==VK_BACK||k==VK_SPACE||k==VK_ESCAPE||k==VK_RETURN||k==VK_NEXT||k==VK_PRIOR||k==VK_OEM_MINUS||k==VK_OEM_PLUS||(k>='1'&&k<='5'));
    }
    bool shiftKey(WPARAM k){return k==VK_SHIFT||k==VK_LSHIFT||k==VK_RSHIFT;}
    void observeDown(WPARAM k,LPARAM flags){
        if(!shiftKey(k)){shiftArmed=false;return;}
        if(flags&(1L<<30))return; // Auto-repeat preserves the original gesture.
        BYTE keys[256]{};
        shiftArmed=GetKeyboardState(keys)!=FALSE;
        for(int key=1;shiftArmed&&key<256;++key)
            if(!shiftKey(key)&&(keys[key]&0x80))shiftArmed=false;
        if((keys[VK_LSHIFT]&keys[VK_RSHIFT]&0x80)!=0)shiftArmed=false;
    }
public:
    Tip(){InterlockedIncrement(&objects);client=std::to_wstring(GetCurrentProcessId())+L"."+std::to_wstring(GetCurrentThreadId())+L"."+std::to_wstring((uintptr_t)this);}
    ~Tip(){if(popup)DestroyWindow(popup);InterlockedDecrement(&objects);}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID i,void**p) override{
        if(i==IID_IUnknown||i==IID_ITfTextInputProcessor)*p=(ITfTextInputProcessor*)this;
        else if(i==IID_ITfKeyEventSink)*p=(ITfKeyEventSink*)this;
        else if(i==IID_ITfThreadMgrEventSink)*p=(ITfThreadMgrEventSink*)this;
        else if(i==IID_ITfTextEditSink)*p=(ITfTextEditSink*)this;else{*p=nullptr;return E_NOINTERFACE;}AddRef();return S_OK;}
    ULONG STDMETHODCALLTYPE AddRef() override{return InterlockedIncrement(&refs);}
    ULONG STDMETHODCALLTYPE Release() override{auto n=InterlockedDecrement(&refs);if(!n)delete this;return n;}
    HRESULT STDMETHODCALLTYPE Activate(ITfThreadMgr*m,TfClientId tid) override{
        mgr=m;mgr->AddRef();id=tid;ITfKeystrokeMgr* keys=nullptr;HRESULT hr=m->QueryInterface(IID_ITfKeystrokeMgr,(void**)&keys);
        if(SUCCEEDED(hr)){hr=keys->AdviseKeyEventSink(id,this,TRUE);keys->Release();}
        if(FAILED(hr)){drop(mgr);return hr;}
        advise(m,IID_ITfThreadMgrEventSink,(ITfThreadMgrEventSink*)this,focusCookie);return S_OK;}
    HRESULT STDMETHODCALLTYPE Deactivate() override{
        clear(true);bind(nullptr);unadvise(mgr,focusCookie);ITfKeystrokeMgr* keys=nullptr;
        if(mgr&&SUCCEEDED(mgr->QueryInterface(IID_ITfKeystrokeMgr,(void**)&keys))){keys->UnadviseKeyEventSink(id);keys->Release();}
        drop(mgr);return S_OK;}
    HRESULT STDMETHODCALLTYPE OnSetFocus(BOOL f) override{if(!f){shiftArmed=false;clear(true);}return S_OK;}
    HRESULT STDMETHODCALLTYPE OnSetFocus(ITfDocumentMgr* now,ITfDocumentMgr*) override{
        ITfContext*c=nullptr;if(now)now->GetTop(&c);bind(c);drop(c);return S_OK;}
    HRESULT STDMETHODCALLTYPE OnInitDocumentMgr(ITfDocumentMgr*) override{return S_OK;}
    HRESULT STDMETHODCALLTYPE OnUninitDocumentMgr(ITfDocumentMgr*) override{return S_OK;}
    HRESULT STDMETHODCALLTYPE OnPushContext(ITfContext*c) override{bind(c);return S_OK;}
    HRESULT STDMETHODCALLTYPE OnPopContext(ITfContext*) override{bind(nullptr);return S_OK;}
    HRESULT STDMETHODCALLTYPE OnEndEdit(ITfContext*,TfEditCookie,ITfEditRecord*r) override{
        if(ownEditPending){ownEditPending=false;return S_OK;}
        BOOL changed=FALSE;r->GetSelectionStatus(&changed);
        IEnumTfRanges* en=nullptr;ITfRange* ran=nullptr;ULONG n=0;
        if(SUCCEEDED(r->GetTextAndPropertyUpdates(TF_GTP_INCL_TEXT,nullptr,0,&en))){en->Next(1,&ran,&n);drop(ran);drop(en);}
        if(changed||n)clear(true);return S_OK;}
    HRESULT STDMETHODCALLTYPE OnTestKeyDown(ITfContext*c,WPARAM k,LPARAM flags,BOOL*eat) override{
        bind(c);observeDown(k,flags);*eat=shiftKey(k)?shiftArmed&&allowed():wants(k)&&allowed();return S_OK;}
    HRESULT STDMETHODCALLTYPE OnTestKeyUp(ITfContext*c,WPARAM k,LPARAM,BOOL*eat) override{
        *eat=c==ctx&&shiftKey(k)&&shiftArmed;return S_OK;}
    HRESULT STDMETHODCALLTYPE OnKeyUp(ITfContext*c,WPARAM k,LPARAM,BOOL*eat) override{
        *eat=FALSE;
        if(c!=ctx||!shiftKey(k)||!shiftArmed)return S_OK;
        shiftArmed=false;
        if(pending||!allowed())return S_OK;
        *eat=TRUE;
        if(!english&&!raw.empty())insert(raw,-1,true);
        else{english=!english;clear(true);display(true);}
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE OnPreservedKey(ITfContext*,REFGUID,BOOL*eat) override{shiftArmed=false;*eat=FALSE;return S_OK;}
    HRESULT STDMETHODCALLTYPE OnKeyDown(ITfContext*c,WPARAM k,LPARAM flags,BOOL*eat) override{
        bind(c);observeDown(k,flags);*eat=FALSE;
        bool shifted=GetKeyState(VK_SHIFT)<0;
        bool pageKey=!shifted&&!raw.empty()&&(k==VK_OEM_MINUS||k==VK_OEM_PLUS);
        if(!english&&!pageKey&&!(k==VK_OEM_7&&!shifted&&!raw.empty())){
            wstring punctuation=punctuationFor(k,shifted);
            if(!punctuation.empty()){
                if(k==VK_OEM_7){
                    if(shifted)doubleQuoteOpen=!doubleQuoteOpen;
                    else singleQuoteOpen=!singleQuoteOpen;
                }
                if(!allowed()){clear(true);return S_OK;}
                *eat=TRUE;
                punctuate(punctuation);
                return S_OK;
            }
        }
        if(!wants(k))return S_OK;if(!allowed()){clear(true);return S_OK;}*eat=TRUE;
        if(k==VK_ESCAPE){clear(false);return S_OK;}if(pending)return S_OK;
        if(k==VK_RETURN){insert(raw,-1);return S_OK;}
        if(k==VK_SPACE||(k>='1'&&k<='5')){choose(k==VK_SPACE?0:int(k-'1'));return S_OK;}
        if(k==VK_NEXT||k==VK_PRIOR||k==VK_OEM_MINUS||k==VK_OEM_PLUS){turn((k==VK_NEXT||k==VK_OEM_PLUS)?1:-1);return S_OK;}
        if(k==VK_BACK)raw.pop_back();else if(raw.size()<96)raw+=k==VK_OEM_7?L'\'':wchar_t(k-'A'+'a');
        if(raw.empty())clear(false);else{page=0;show(call(client,L"input",raw));}return S_OK;}
};
class Factory : public IClassFactory {
    LONG refs=1;
public:
    Factory(){InterlockedIncrement(&objects);}~Factory(){InterlockedDecrement(&objects);}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID i,void**p) override{if(i!=IID_IUnknown&&i!=IID_IClassFactory){*p=nullptr;return E_NOINTERFACE;}*p=this;AddRef();return S_OK;}
    ULONG STDMETHODCALLTYPE AddRef() override{return ++refs;}ULONG STDMETHODCALLTYPE Release() override{auto n=--refs;if(!n)delete this;return n;}
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer,REFIID i,void**p) override{if(outer)return CLASS_E_NOAGGREGATION;auto t=new Tip;auto h=t->QueryInterface(i,p);t->Release();return h;}
    HRESULT STDMETHODCALLTYPE LockServer(BOOL l) override{if(l)InterlockedIncrement(&objects);else InterlockedDecrement(&objects);return S_OK;}
};
extern "C" __declspec(dllexport) HRESULT WINAPI DllGetClassObject(REFCLSID c,REFIID i,void**p){
    if(c!=tipId)return CLASS_E_CLASSNOTAVAILABLE;auto f=new Factory;auto h=f->QueryInterface(i,p);f->Release();return h;}
extern "C" __declspec(dllexport) HRESULT WINAPI DllCanUnloadNow(){return objects==0?S_OK:S_FALSE;}
BOOL WINAPI DllMain(HINSTANCE inst,DWORD why,void*){if(why==DLL_PROCESS_ATTACH){module=inst;DisableThreadLibraryCalls(inst);}return TRUE;}
static HRESULT registration(bool add){
    bool initialized=SUCCEEDED(CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED));
    ITfInputProcessorProfileMgr* profiles=nullptr;ITfCategoryMgr* cats=nullptr;
    auto hr=CoCreateInstance(CLSID_TF_InputProcessorProfiles,nullptr,CLSCTX_INPROC_SERVER,IID_ITfInputProcessorProfileMgr,(void**)&profiles);
    wstring path=dllPath(),desc=L"改革拼音";wchar_t guid[40];StringFromGUID2(tipId,guid,40);
    wstring key=wstring(L"Software\\Classes\\CLSID\\")+guid;
    if(SUCCEEDED(hr))hr=CoCreateInstance(CLSID_TF_CategoryMgr,nullptr,CLSCTX_INPROC_SERVER,IID_ITfCategoryMgr,(void**)&cats);
    if(SUCCEEDED(hr)&&add){
        wstring in=key+L"\\InprocServer32";LONG res=RegSetKeyValueW(HKEY_LOCAL_MACHINE,in.c_str(),nullptr,REG_SZ,path.c_str(),DWORD((path.size()+1)*2));
        if(!res)res=RegSetKeyValueW(HKEY_LOCAL_MACHINE,in.c_str(),L"ThreadingModel",REG_SZ,L"Apartment",20);
        hr=HRESULT_FROM_WIN32(res);
        if(SUCCEEDED(hr))hr=profiles->RegisterProfile(tipId,0x0804,profileId,desc.data(),desc.size(),path.data(),path.size(),0,0,0,TRUE,0);
        if(SUCCEEDED(hr))hr=cats->RegisterCategory(tipId,GUID_TFCAT_TIP_KEYBOARD,tipId);
        if(FAILED(hr)){
            profiles->UnregisterProfile(tipId,0x0804,profileId,0);
            RegDeleteTreeW(HKEY_LOCAL_MACHINE,key.c_str());
        }
    }else if(SUCCEEDED(hr)){cats->UnregisterCategory(tipId,GUID_TFCAT_TIP_KEYBOARD,tipId);hr=profiles->UnregisterProfile(tipId,0x0804,profileId,0);RegDeleteTreeW(HKEY_LOCAL_MACHINE,key.c_str());}
    drop(profiles);drop(cats);if(initialized)CoUninitialize();return hr;}
extern "C" __declspec(dllexport) HRESULT WINAPI DllRegisterServer(){return registration(true);}
extern "C" __declspec(dllexport) HRESULT WINAPI DllUnregisterServer(){return registration(false);}
