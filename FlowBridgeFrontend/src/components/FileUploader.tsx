import {ChangeEvent, useState} from 'react';
import "../App.css"

type uploadStatus = "idle" | "uploading" | "success" | "error";

export default function FileUploader(){
    const [file, setFile] = useState<File | null>(null);
    //Setting default state for the status of a file upload
    const [status, setStatus] = useState<uploadStatus>("idle");

    function handleFileChange(e: ChangeEvent<HTMLInputElement>){
        if(e.target.files){
            setFile(e.target.files[0])
        }
    }
    return (
        <>
            <label htmlFor="fileUpload">
                <img src="UploadFileButton.png" alt="Upload Icon" className = "toolIcon"/>
            </label>
            <input type="file" id="fileUpload" className = "toolButton" onChange={handleFileChange}></input>
        </>
    );
}