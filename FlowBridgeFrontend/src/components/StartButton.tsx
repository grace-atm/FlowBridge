import {ChangeEvent, useState} from 'react';
import "../App.css"
import FileUploader from './FileUploader';

export default function StartButton(){
    return(
        <>
            <div className="headingCenter">
                <button className="startButton">
                    <img src="./StartButton.png" alt="Start Button"/>
                </button>
            </div>
        </>
    );
}
