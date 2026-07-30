'use client';


import { useState } from 'react';
import { useRouter } from 'next/navigation';

import { useProjects } from '@/hooks/useProjects';

import {
  PLATFORMS,
  MARKETS
} from '@/lib/constants';



export default function CreateProjectPage(){


  const router = useRouter();


  const {
    createProject
  } = useProjects();



  const [name,setName] = useState('');

  const [platform,setPlatform] = useState(
    'Amazon'
  );

  const [market,setMarket] = useState(
    'USA'
  );


  const [loading,setLoading] = useState(false);



  const handleSubmit = async(
    e:React.FormEvent
  )=>{


    e.preventDefault();


    setLoading(true);


    try{


      const project =
        await createProject(
          name,
          platform,
          market
        );


      router.push(
        `/projects/${project.id}`
      );


    }finally{

      setLoading(false);

    }


  };




  return (

    <div className="max-w-xl mx-auto px-4 py-8">


      <h1 className="text-3xl font-bold mb-6">

        Create Project

      </h1>



      <form
        onSubmit={handleSubmit}
        className="
        bg-white
        border
        rounded-xl
        p-6
        space-y-5
        "
      >


        <div>

          <label className="block text-sm font-medium mb-1">

            Project Name

          </label>


          <input

            value={name}

            onChange={
              e=>setName(e.target.value)
            }

            required

            placeholder="Example: Bluetooth Earbuds"

            className="
            w-full
            border
            rounded-lg
            px-4
            py-2
            "

          />


        </div>




        <div>


          <label className="block text-sm font-medium mb-1">

            Platform

          </label>


          <select

            value={platform}

            onChange={
              e=>setPlatform(e.target.value)
            }

            className="
            w-full
            border
            rounded-lg
            px-4
            py-2
            "

          >

            {
              PLATFORMS.map(item=>(

                <option key={item}>
                  {item}
                </option>

              ))
            }


          </select>


        </div>





        <div>


          <label className="block text-sm font-medium mb-1">

            Market

          </label>


          <select

            value={market}

            onChange={
              e=>setMarket(e.target.value)
            }


            className="
            w-full
            border
            rounded-lg
            px-4
            py-2
            "

          >


            {
              MARKETS.map(item=>(

                <option key={item}>
                  {item}
                </option>

              ))
            }


          </select>


        </div>





        <button

          disabled={loading}

          className="
          w-full
          bg-blue-600
          text-white
          py-2.5
          rounded-lg
          hover:bg-blue-700
          disabled:opacity-50
          "

        >

          {
            loading
            ?
            'Creating...'
            :
            'Create Project'
          }


        </button>


      </form>


    </div>

  );


}