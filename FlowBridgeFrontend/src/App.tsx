import FileUploader from "./components/FileUploader";
import StartButton from "./components/StartButton";
import axios from "axios";

const api = axios.create({
    baseURL: "http://localhost:8000"
})

function app(){
  return <>
        <head>
            <meta charSet="UTF-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
            <title>FlowBridge</title>
        </head>
        <header className="heading">
            <div className="headingLeft">
                <img src="./FlowBridgeIcon.png" alt="Logo Icon" className="logoIcon"/>
                <span className="brandName">FlowBridge</span>
            </div>
                <StartButton/>
            <div className="headingRight">
                <div className="user-profile">
                    <div>
                        <label htmlFor="loginButton">
                            <img src="./ProfilePicture.png" alt="Profile Icon" className="loginIcon"/>
                        </label>
                        <input type="button" id="loginButton" className="toolButton"/>
                    </div>
                </div>
            </div>
      </header>
      <div className="workspace">
            <aside className="sidebarLeft">
                <div className="toolbarTop">
                    <div>
                        <FileUploader/>
                    </div>
                    <img src="ExportButton.png" alt="Export Icon" className="toolIcon"/>
                </div>
                <div className="toolbar-bottom">
                    <img src="SettingsIcon.png" alt="Settings Icon" className="toolIcon"/>
                </div>
            </aside>
            <main className="contentGrid">
                <section className="card">
                    <div className="cardHeader">
                        Source Code
                    </div>
                        <iframe 
                            src="https://onecompiler.com/embed/python?hideResult=true&hideRun=true&listenToEvents=true&codeChangeEvent=true" 
                            width="100%" 
                            height="100%" 
                            id="codeEditor">
                        </iframe>
                    <div className="cardBody"></div>
                </section>

                <section className="card">
                    <div className="cardHeader">FlowChart</div>
                    <div className="cardBody flowchartBody">
                        <img src="ExampleScreenShot.jpg" alt="Flowchart" className="flowchartImage"/>
                    </div>
                </section>
            </main>
          </div>
  </>;
}

export default app;