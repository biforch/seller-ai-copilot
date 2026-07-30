'use client';

import { useCallback, useState } from 'react';

import { apiClient } from '@/app/api/client';

import type { Project } from '@/types';



export function useProjects() {


  const [projects,setProjects] = useState<Project[]>([]);

  const [isLoading,setIsLoading] = useState(false);

  const [error,setError] = useState<string | null>(null);



  const fetchProjects = useCallback(async()=>{


    setIsLoading(true);

    setError(null);


    try{


      const data = await apiClient.get<Project[]>(
        '/projects'
      );


      setProjects(data);



    }catch(err){


      setError(
        err instanceof Error
        ? err.message
        : "Failed to fetch projects"
      );


    }finally{


      setIsLoading(false);


    }


  },[]);





  const createProject = useCallback(
    async(
      name:string,
      platform:string,
      market:string
    )=>{


      const data =
        await apiClient.post<Project>(
          '/projects',
          {
            name,
            platform,
            market
          }
        );


      setProjects(
        prev=>[
          data,
          ...prev
        ]
      );


      return data;


    },
    []
  );



  return {

    projects,

    isLoading,

    error,

    fetchProjects,

    createProject

  };


}